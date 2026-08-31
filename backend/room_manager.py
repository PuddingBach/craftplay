import asyncio
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import WebSocket
from sqlalchemy import select

from backend.browser.service import browser_service
from backend.browser.livekit import livekit_configured, set_room_privacy
from backend.browser.state import browser_state_store
from backend.browser.settings import browser_setting
from backend.config import get_settings
from backend.database import SessionLocal
from backend.models import BrowserSession, BrowserSessionMember, Room, RoomMember, User


PLAYER_EVENTS = {
    "PLAYER_PLAY", "PLAYER_PAUSE", "PLAYER_SEEK", "PLAYER_SYNC", "MEDIA_CHANGE",
    "EPISODE_CHANGE", "HOST_CHANGE", "GRANT_CONTROL",
}
BROWSER_INPUT_EVENTS = {
    "MOUSE_MOVE", "MOUSE_CLICK", "MOUSE_SCROLL", "KEY_DOWN", "KEY_UP",
    "TEXT_INPUT", "BACK", "FORWARD", "RELOAD", "HOME", "FOCUS",
}
BROWSER_EVENTS = BROWSER_INPUT_EVENTS | {
    "NAVIGATE", "CONTROL_REQUEST", "REQUEST_CONTROL", "CONTROL_GRANTED",
    "CONTROL_REVOKED", "PRIVACY_ON", "PRIVACY_OFF", "SESSION_LOCK",
    "BROWSER_FRAME_REQUEST",
}


class RoomManager:
    def __init__(self):
        self.connections: dict[str, dict[str, WebSocket]] = defaultdict(dict)
        self.profiles: dict[str, dict[str, dict]] = defaultdict(dict)
        self.input_windows: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        self.pending_connections: dict[str, set[str]] = defaultdict(set)
        self.empty_cleanup_tasks: dict[str, asyncio.Task] = {}
        self.lock = asyncio.Lock()

    async def connect(self, room_id: str, discord_id: str, websocket: WebSocket, profile: dict, *, already_accepted: bool = False) -> Room:
        async with self.lock:
            is_new = discord_id not in self.connections[room_id] and discord_id not in self.pending_connections[room_id]
            if is_new and len(self.connections[room_id]) + len(self.pending_connections[room_id]) >= int(browser_setting("max_participants", get_settings().room_max_participants)):
                raise OverflowError("Esta sessao atingiu o limite de participantes")
            self.pending_connections[room_id].add(discord_id)
        with SessionLocal() as db:
            room = db.get(Room, room_id)
            if not room:
                raise ValueError("Sala nao encontrada")
            browser = db.scalar(select(BrowserSession).where(BrowserSession.room_id == room_id, BrowserSession.closed_at.is_(None)))
            host_discord_id = self._discord_id_for_user(room.host_user_id)
            if browser and browser.session_locked and discord_id != host_discord_id:
                raise PermissionError("Esta sessao esta bloqueada")
            user = db.scalar(select(User).where(User.discord_id == discord_id))
            if not user:
                user = User(discord_id=discord_id, username=profile.get("username", "Participante"), avatar=profile.get("avatar"))
                db.add(user); db.flush()
            member = db.scalar(select(RoomMember).where(RoomMember.room_id == room_id, RoomMember.user_id == user.id))
            if not member:
                db.add(RoomMember(room_id=room_id, user_id=user.id))
            if room.host_user_id is None:
                room.host_user_id = user.id
            if browser:
                membership = db.scalar(select(BrowserSessionMember).where(BrowserSessionMember.session_id == browser.id, BrowserSessionMember.user_id == user.id))
                if membership: membership.last_seen_at = datetime.now(timezone.utc)
                else: db.add(BrowserSessionMember(session_id=browser.id, user_id=user.id))
            db.commit(); db.refresh(room)

        if not already_accepted:
            await websocket.accept()
        async with self.lock:
            self.pending_connections[room_id].discard(discord_id)
            self.connections[room_id][discord_id] = websocket
            self.profiles[room_id][discord_id] = profile
        cleanup = self.empty_cleanup_tasks.pop(room_id, None)
        if cleanup: cleanup.cancel()
        await self.broadcast(room_id, self.snapshot(room, "ROOM_JOIN", discord_id))
        return room

    async def disconnect(self, room_id: str, discord_id: str) -> None:
        async with self.lock:
            self.connections[room_id].pop(discord_id, None)
            self.profiles[room_id].pop(discord_id, None)
        host_changed = False
        with SessionLocal() as db:
            room = db.get(Room, room_id)
            departing = db.scalar(select(User).where(User.discord_id == discord_id))
            if room and departing and room.host_user_id == departing.id:
                next_discord_id = next(iter(self.connections[room_id]), None)
                next_user = db.scalar(select(User).where(User.discord_id == next_discord_id)) if next_discord_id else None
                if next_user:
                    room.host_user_id = next_user.id
                    room.controllers = []
                    browser = db.scalar(select(BrowserSession).where(BrowserSession.room_id == room_id, BrowserSession.closed_at.is_(None)))
                    if browser:
                        browser.host_user_id = next_user.id; browser.controller_user_id = None; browser.control_expires_at = None
                    db.commit(); db.refresh(room); host_changed = True
                    await self.broadcast(room_id, self.snapshot(room, "HOST_CHANGE", discord_id))
        if not host_changed:
            await self.broadcast(room_id, {"event": "ROOM_LEAVE", "user_id": discord_id, "participants": list(self.profiles[room_id].values())})
        if not self.connections[room_id]:
            self.empty_cleanup_tasks[room_id] = asyncio.create_task(self._cleanup_empty_room(room_id))

    def snapshot(self, room: Room, event: str = "PLAYER_SYNC", actor: str | None = None) -> dict:
        elapsed = 0
        if room.state == "playing" and room.updated_at:
            updated = room.updated_at.replace(tzinfo=timezone.utc) if room.updated_at.tzinfo is None else room.updated_at
            elapsed = max(0, (datetime.now(timezone.utc) - updated).total_seconds()) * room.playback_rate
        payload = {
            "event": event, "room_id": room.id, "user_id": actor,
            "host_user_id": self._discord_id_for_user(room.host_user_id),
            "media_id": room.current_media, "season": room.current_season, "episode": room.current_episode,
            "position": room.position + elapsed, "state": room.state, "playback_rate": room.playback_rate,
            "subtitle": room.subtitle, "audio_track": room.audio_track,
            "controllers": room.controllers or [], "timestamp": int(time.time() * 1000),
            "participants": list(self.profiles[room.id].values()),
        }
        with SessionLocal() as db:
            browser = db.scalar(select(BrowserSession).where(BrowserSession.room_id == room.id, BrowserSession.closed_at.is_(None)))
            if browser:
                controller = db.get(User, browser.controller_user_id) if browser.controller_user_id else None
                payload["browser"] = {
                    "session_id": browser.id, "status": browser.browser_status, "current_url": browser.current_url,
                    "current_entry_id": browser.current_entry_id, "control_mode": browser.control_mode,
                    "controller_user_id": controller.discord_id if controller else None,
                    "control_queue": browser.control_queue or [], "privacy_mode": browser.privacy_mode,
                    "session_locked": browser.session_locked, "shield_mode": browser.shield_mode,
                    "max_participants": int(browser_setting("max_participants", get_settings().room_max_participants)),
                }
        return payload

    @staticmethod
    def _discord_id_for_user(user_id: int | None) -> str | None:
        if not user_id: return None
        with SessionLocal() as db:
            user = db.get(User, user_id)
            return user.discord_id if user else None

    def can_control_player(self, room: Room, discord_id: str) -> bool:
        return discord_id == self._discord_id_for_user(room.host_user_id) or discord_id in (room.controllers or [])

    async def handle(self, room_id: str, discord_id: str, payload: dict) -> None:
        event = str(payload.get("event", ""))
        if event in BROWSER_EVENTS:
            await self._handle_browser(room_id, discord_id, event, payload); return
        with SessionLocal() as db:
            room = db.get(Room, room_id)
            if not room: return
            if event in PLAYER_EVENTS and not self.can_control_player(room, discord_id):
                await self.send(room_id, discord_id, {"event": "ERROR", "code": "CONTROL_DENIED", "message": "Apenas usuarios autorizados podem controlar o player."}); return
            position = max(0.0, float(payload.get("position", room.position)))
            if event == "PLAYER_PLAY": room.position, room.state = position, "playing"
            elif event == "PLAYER_PAUSE": room.position, room.state = position, "paused"
            elif event in {"PLAYER_SEEK", "PLAYER_SYNC"}: room.position = position
            elif event == "MEDIA_CHANGE":
                room.current_media, room.current_season, room.current_episode = payload.get("media_id"), int(payload.get("season", 0)), int(payload.get("episode", 0)); room.position, room.state = 0, "paused"
            elif event == "EPISODE_CHANGE":
                room.current_season, room.current_episode = int(payload.get("season", 0)), int(payload.get("episode", 0)); room.position, room.state = 0, "paused"
            elif event == "HOST_CHANGE":
                target_id = str(payload.get("target_user_id")); target = db.scalar(select(User).where(User.discord_id == target_id)) if target_id in self.profiles[room_id] else None
                if target: room.host_user_id = target.id
            elif event == "GRANT_CONTROL":
                target_id = str(payload.get("target_user_id")); controllers = list(room.controllers or [])
                if target_id and target_id not in controllers: controllers.append(target_id)
                room.controllers = controllers
            if "playback_rate" in payload: room.playback_rate = min(2.0, max(0.25, float(payload["playback_rate"])))
            if "subtitle" in payload: room.subtitle = payload["subtitle"]
            if "audio_track" in payload: room.audio_track = payload["audio_track"]
            room.updated_at = datetime.now(timezone.utc); db.commit(); db.refresh(room)
            await self.broadcast(room_id, self.snapshot(room, event, discord_id))

    async def _handle_browser(self, room_id: str, discord_id: str, event: str, payload: dict) -> None:
        if event in BROWSER_INPUT_EVENTS and not self._within_rate_limit(room_id, discord_id, event):
            await self.send(room_id, discord_id, {"event": "ERROR", "code": "RATE_LIMIT", "message": "Muitos comandos em sequencia."}); return
        with SessionLocal() as db:
            room = db.get(Room, room_id)
            session = db.scalar(select(BrowserSession).where(BrowserSession.room_id == room_id, BrowserSession.closed_at.is_(None)))
            actor = db.scalar(select(User).where(User.discord_id == discord_id))
            if not room or not session or not actor:
                await self.send(room_id, discord_id, {"event": "BROWSER_ERROR", "message": "Sessao de navegador indisponivel."}); return
            host_id = self._discord_id_for_user(room.host_user_id); is_host = discord_id == host_id; now = datetime.now(timezone.utc)
            expiry = session.control_expires_at
            if expiry and expiry.tzinfo is None: expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry and expiry <= now: session.controller_user_id = None; session.control_expires_at = None
            controller_id = self._discord_id_for_user(session.controller_user_id)
            can_control = is_host or session.control_mode == "SHARED" or controller_id == discord_id
            if event == "BROWSER_FRAME_REQUEST":
                if session.privacy_mode and not is_host:
                    return
                try:
                    await self.send(room_id, discord_id, await browser_service.capture_frame(room_id))
                except Exception as exc:
                    await self.send(room_id, discord_id, {"event": "BROWSER_ERROR", "message": str(exc)})
                return
            if event in {"CONTROL_REQUEST", "REQUEST_CONTROL"}:
                if session.control_mode == "HOST_ONLY":
                    await self.send(room_id, discord_id, {"event": "ERROR", "code": "CONTROL_DENIED", "message": "Esta sala permite controle apenas do host."}); return
                queue = list(session.control_queue or [])
                if discord_id != host_id and discord_id not in [item.get("user_id") for item in queue]:
                    queue.append({"user_id": discord_id, "username": self.profiles[room_id].get(discord_id, {}).get("username", "Participante"), "requested_at": now.isoformat()}); session.control_queue = queue
                db.commit(); await self.broadcast(room_id, {"event": "CONTROL_REQUEST", "user_id": discord_id, "control_queue": queue}); return
            if event == "CONTROL_GRANTED":
                if not is_host:
                    await self.send(room_id, discord_id, {"event": "ERROR", "code": "CONTROL_DENIED", "message": "Somente o host concede controle."}); return
                target_id = str(payload.get("target_user_id", "")); target = db.scalar(select(User).where(User.discord_id == target_id))
                if not target or target_id not in self.connections[room_id]:
                    await self.send(room_id, discord_id, {"event": "ERROR", "code": "USER_NOT_FOUND", "message": "Participante nao encontrado."}); return
                session.controller_user_id = target.id; session.control_expires_at = now + timedelta(seconds=get_settings().control_idle_timeout)
                session.control_queue = [item for item in (session.control_queue or []) if item.get("user_id") != target_id]
                db.commit(); await self.broadcast(room_id, {"event": "CONTROL_GRANTED", "user_id": target_id, "expires_at": session.control_expires_at.isoformat(), "control_queue": session.control_queue}); return
            if event == "CONTROL_REVOKED":
                if not is_host:
                    await self.send(room_id, discord_id, {"event": "ERROR", "code": "CONTROL_DENIED", "message": "Somente o host revoga controle."}); return
                session.controller_user_id = None; session.control_expires_at = None; db.commit(); await self.broadcast(room_id, {"event": "CONTROL_REVOKED", "user_id": discord_id}); return
            if event in {"PRIVACY_ON", "PRIVACY_OFF", "SESSION_LOCK"}:
                if not is_host:
                    await self.send(room_id, discord_id, {"event": "ERROR", "code": "CONTROL_DENIED", "message": "Somente o host altera esta opcao."}); return
                if event.startswith("PRIVACY"):
                    session.privacy_mode = event == "PRIVACY_ON"
                    if session.privacy_mode: session.controller_user_id = None; session.control_expires_at = None
                    if livekit_configured():
                        try: await set_room_privacy(session.stream_room_name, host_id, session.privacy_mode)
                        except RuntimeError as exc:
                            await self.send(room_id, discord_id, {"event": "BROWSER_ERROR", "message": str(exc)}); return
                else: session.session_locked = bool(payload.get("locked", True))
                db.commit(); await self.broadcast(room_id, {"event": event, "privacy_mode": session.privacy_mode, "session_locked": session.session_locked}); return
            if not can_control or (session.privacy_mode and not is_host):
                await self.send(room_id, discord_id, {"event": "ERROR", "code": "CONTROL_DENIED", "message": "Voce nao possui controle do navegador."}); return
            try:
                if event == "NAVIGATE": session.current_url = await browser_service.navigate(room_id, str(payload.get("url", "")))
                else: await browser_service.action(room_id, event, payload)
            except (ValueError, RuntimeError) as exc:
                await self.send(room_id, discord_id, {"event": "BROWSER_ERROR", "message": str(exc)}); return
            if not is_host: session.control_expires_at = now + timedelta(seconds=get_settings().control_idle_timeout)
            session.last_activity_at = now; db.commit()
            await self.broadcast(room_id, {"event": event, "user_id": discord_id, "current_url": session.current_url, "x": payload.get("x"), "y": payload.get("y"), "timestamp": int(time.time() * 1000)})

    def _within_rate_limit(self, room_id: str, discord_id: str, event: str) -> bool:
        limit = 60 if event == "MOUSE_MOVE" else 30 if event == "MOUSE_SCROLL" else 50
        now = time.monotonic(); key = (room_id, discord_id, event); window = [stamp for stamp in self.input_windows[key] if stamp > now - 1]
        if len(window) >= limit: self.input_windows[key] = window; return False
        window.append(now); self.input_windows[key] = window; return True

    async def _cleanup_empty_room(self, room_id: str) -> None:
        try:
            await asyncio.sleep(get_settings().empty_room_grace_period)
            if self.connections[room_id]: return
            await browser_service.close(room_id)
            await browser_state_store.delete(room_id)
            with SessionLocal() as db:
                session = db.scalar(select(BrowserSession).where(BrowserSession.room_id == room_id, BrowserSession.closed_at.is_(None)))
                if session: session.browser_status = "CLOSED"; session.closed_at = datetime.now(timezone.utc); db.commit()
        finally: self.empty_cleanup_tasks.pop(room_id, None)

    async def send(self, room_id: str, discord_id: str, payload: dict) -> None:
        socket = self.connections[room_id].get(discord_id)
        if socket: await socket.send_json(payload)

    def release_pending(self, room_id: str, discord_id: str) -> None:
        self.pending_connections[room_id].discard(discord_id)

    async def broadcast(self, room_id: str, payload: dict) -> None:
        if payload.get("event") not in {"MOUSE_MOVE", "MOUSE_CLICK", "MOUSE_SCROLL", "KEY_DOWN", "KEY_UP", "TEXT_INPUT"}:
            await browser_state_store.put(room_id, payload)
        stale = []
        for discord_id, socket in list(self.connections[room_id].items()):
            try: await socket.send_json(payload)
            except Exception: stale.append(discord_id)
        for discord_id in stale:
            self.connections[room_id].pop(discord_id, None); self.profiles[room_id].pop(discord_id, None)

    async def broadcast_browser_frame(self, room_id: str, payload: dict) -> None:
        targets = list(self.connections[room_id].items())
        if not targets:
            return
        with SessionLocal() as db:
            room = db.get(Room, room_id)
            session = db.scalar(select(BrowserSession).where(BrowserSession.room_id == room_id, BrowserSession.closed_at.is_(None)))
            if room and session and session.privacy_mode:
                host_id = self._discord_id_for_user(room.host_user_id)
                targets = [(discord_id, socket) for discord_id, socket in targets if discord_id == host_id]
        stale = []
        for discord_id, socket in targets:
            try:
                await socket.send_json(payload)
            except Exception:
                stale.append(discord_id)
        for discord_id in stale:
            self.connections[room_id].pop(discord_id, None)
            self.profiles[room_id].pop(discord_id, None)


room_manager = RoomManager()
