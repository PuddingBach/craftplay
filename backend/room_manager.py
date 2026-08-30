import asyncio
import time
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import WebSocket
from sqlalchemy import select

from backend.database import SessionLocal
from backend.models import Room, RoomMember, User


CONTROL_EVENTS = {
    "PLAYER_PLAY", "PLAYER_PAUSE", "PLAYER_SEEK", "PLAYER_SYNC", "MEDIA_CHANGE",
    "EPISODE_CHANGE", "HOST_CHANGE", "GRANT_CONTROL",
}


class RoomManager:
    def __init__(self):
        self.connections: dict[str, dict[str, WebSocket]] = defaultdict(dict)
        self.profiles: dict[str, dict[str, dict]] = defaultdict(dict)
        self.lock = asyncio.Lock()

    async def connect(self, room_id: str, discord_id: str, websocket: WebSocket, profile: dict) -> Room:
        await websocket.accept()
        async with self.lock:
            self.connections[room_id][discord_id] = websocket
            self.profiles[room_id][discord_id] = profile
        with SessionLocal() as db:
            room = db.get(Room, room_id)
            if not room:
                raise ValueError("Sala não encontrada")
            user = db.scalar(select(User).where(User.discord_id == discord_id))
            if not user:
                user = User(discord_id=discord_id, username=profile.get("username", "Participante"), avatar=profile.get("avatar"))
                db.add(user)
                db.flush()
            member = db.scalar(select(RoomMember).where(RoomMember.room_id == room_id, RoomMember.user_id == user.id))
            if not member:
                db.add(RoomMember(room_id=room_id, user_id=user.id))
            if room.host_user_id is None:
                room.host_user_id = user.id
            db.commit()
            db.refresh(room)
            await self.broadcast(room_id, self.snapshot(room, "ROOM_JOIN", discord_id))
            return room

    async def disconnect(self, room_id: str, discord_id: str) -> None:
        async with self.lock:
            self.connections[room_id].pop(discord_id, None)
            self.profiles[room_id].pop(discord_id, None)
        with SessionLocal() as db:
            room = db.get(Room, room_id)
            departing = db.scalar(select(User).where(User.discord_id == discord_id))
            if room and departing and room.host_user_id == departing.id:
                next_discord_id = next(iter(self.connections[room_id]), None)
                next_user = db.scalar(select(User).where(User.discord_id == next_discord_id)) if next_discord_id else None
                room.host_user_id = next_user.id if next_user else None
                room.controllers = []
                db.commit()
                db.refresh(room)
                await self.broadcast(room_id, self.snapshot(room, "HOST_CHANGE", discord_id))
                return
        await self.broadcast(room_id, {"event": "ROOM_LEAVE", "user_id": discord_id, "participants": list(self.profiles[room_id].values())})

    def snapshot(self, room: Room, event: str = "PLAYER_SYNC", actor: str | None = None) -> dict:
        elapsed = 0
        if room.state == "playing" and room.updated_at:
            updated = room.updated_at.replace(tzinfo=timezone.utc) if room.updated_at.tzinfo is None else room.updated_at
            elapsed = max(0, (datetime.now(timezone.utc) - updated).total_seconds()) * room.playback_rate
        return {
            "event": event, "room_id": room.id, "user_id": actor,
            "host_user_id": self._discord_id_for_user(room.host_user_id),
            "media_id": room.current_media, "season": room.current_season, "episode": room.current_episode,
            "position": room.position + elapsed, "state": room.state, "playback_rate": room.playback_rate,
            "subtitle": room.subtitle, "audio_track": room.audio_track,
            "controllers": room.controllers or [], "timestamp": int(time.time() * 1000),
            "participants": list(self.profiles[room.id].values()),
        }

    @staticmethod
    def _discord_id_for_user(user_id: int | None) -> str | None:
        if not user_id:
            return None
        with SessionLocal() as db:
            user = db.get(User, user_id)
            return user.discord_id if user else None

    def can_control(self, room: Room, discord_id: str) -> bool:
        return discord_id == self._discord_id_for_user(room.host_user_id) or discord_id in (room.controllers or [])

    async def handle(self, room_id: str, discord_id: str, payload: dict) -> None:
        event = str(payload.get("event", ""))
        with SessionLocal() as db:
            room = db.get(Room, room_id)
            if not room:
                return
            if event == "REQUEST_CONTROL":
                await self.broadcast(room_id, {"event": event, "user_id": discord_id, "username": self.profiles[room_id].get(discord_id, {}).get("username"), "timestamp": int(time.time() * 1000)})
                return
            if event in CONTROL_EVENTS and not self.can_control(room, discord_id):
                await self.send(room_id, discord_id, {"event": "ERROR", "code": "CONTROL_DENIED", "message": "Apenas o host ou usuários autorizados podem controlar o player."})
                return
            position = max(0.0, float(payload.get("position", room.position)))
            if event == "PLAYER_PLAY":
                room.position, room.state = position, "playing"
            elif event == "PLAYER_PAUSE":
                room.position, room.state = position, "paused"
            elif event in {"PLAYER_SEEK", "PLAYER_SYNC"}:
                room.position = position
            elif event == "MEDIA_CHANGE":
                room.current_media, room.current_season, room.current_episode = payload.get("media_id"), int(payload.get("season", 0)), int(payload.get("episode", 0))
                room.position, room.state = 0, "paused"
            elif event == "EPISODE_CHANGE":
                room.current_season, room.current_episode = int(payload.get("season", 0)), int(payload.get("episode", 0))
                room.position, room.state = 0, "paused"
            elif event == "HOST_CHANGE":
                target_id = str(payload.get("target_user_id"))
                target = db.scalar(select(User).where(User.discord_id == target_id)) if target_id in self.profiles[room_id] else None
                if target:
                    room.host_user_id = target.id
            elif event == "GRANT_CONTROL":
                target_id = str(payload.get("target_user_id"))
                controllers = list(room.controllers or [])
                if target_id and target_id not in controllers:
                    controllers.append(target_id)
                room.controllers = controllers
            if "playback_rate" in payload:
                room.playback_rate = min(2.0, max(0.25, float(payload["playback_rate"])))
            if "subtitle" in payload:
                room.subtitle = payload["subtitle"]
            if "audio_track" in payload:
                room.audio_track = payload["audio_track"]
            room.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(room)
            await self.broadcast(room_id, self.snapshot(room, event, discord_id))

    async def send(self, room_id: str, discord_id: str, payload: dict) -> None:
        socket = self.connections[room_id].get(discord_id)
        if socket:
            await socket.send_json(payload)

    async def broadcast(self, room_id: str, payload: dict) -> None:
        stale = []
        for discord_id, socket in list(self.connections[room_id].items()):
            try:
                await socket.send_json(payload)
            except Exception:
                stale.append(discord_id)
        for discord_id in stale:
            self.connections[room_id].pop(discord_id, None)
            self.profiles[room_id].pop(discord_id, None)


room_manager = RoomManager()
