import asyncio
import logging
import re
import time
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.auth import current_dashboard_admin, current_user, decode_websocket_ticket
from backend.browser.livekit import create_viewer_token, livekit_configured, livekit_health
from backend.browser.security import validate_public_url
from backend.browser.service import browser_service
from backend.browser.state import browser_state_store
from backend.browser.settings import browser_setting
from backend.playback.validation import validate_media_url
from backend.config import get_settings
from backend.database import SessionLocal, get_db
from backend.models import AdminAuditLog, AllowedDomain, BlockedDomain, BrowserEntry, BrowserFavorite, BrowserHistory, BrowserSession, BrowserSetting, Room, User
from backend.providers import CatalogService
from backend.schemas import BrowserEntryCreate, BrowserEntryUpdate, BrowserEntryView, BrowserInputCommand, BrowserNavigate, BrowserSessionAction, BrowserSessionStart, BrowserTestRequest


router = APIRouter(prefix="/api/browser", tags=["browser"])
dashboard_router = APIRouter(prefix="/api/dashboard/browser", tags=["dashboard-browser"])
catalog = CatalogService()
logger = logging.getLogger("craftplay.browser.api")


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-") or "entry"


def unique_slug(db: Session, requested: str, entry_id: int | None = None) -> str:
    base, candidate, suffix = requested, requested, 2
    while db.scalar(select(BrowserEntry.id).where(BrowserEntry.slug == candidate, BrowserEntry.id != entry_id)):
        candidate, suffix = f"{base}-{suffix}", suffix + 1
    return candidate


def audit(db: Session, user: User, action: str, target: str, target_id=None, details=None) -> None:
    db.add(AdminAuditLog(user_id=user.id, action=action, target_type=target, target_id=str(target_id) if target_id is not None else None, details=details or {}))


def is_host(db: Session, room: Room, user: User) -> bool:
    return room.host_user_id == user.id


def may_control(session: BrowserSession, room: Room, user: User) -> bool:
    now = datetime.now(timezone.utc)
    expiry = session.control_expires_at
    if expiry and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return is_host(None, room, user) or (
        session.controller_user_id == user.id and (not expiry or expiry > now)
    ) or session.control_mode == "SHARED"


def serialize_session(db: Session, session: BrowserSession) -> dict:
    room = db.get(Room, session.room_id)
    host = db.get(User, session.host_user_id)
    controller = db.get(User, session.controller_user_id) if session.controller_user_id else None
    from backend.room_manager import room_manager
    participants = len(room_manager.connections.get(session.room_id, {}))
    return {
        "id": session.id, "room_id": session.room_id,
        "host_user_id": host.discord_id if host else None,
        "controller_user_id": controller.discord_id if controller else None,
        "participants": participants, "max_participants": int(browser_setting("max_participants", get_settings().room_max_participants)),
        "current_url": session.current_url, "current_entry_id": session.current_entry_id,
        "control_mode": session.control_mode, "privacy_mode": session.privacy_mode,
        "session_locked": session.session_locked, "browser_status": session.browser_status,
        "shield_mode": session.shield_mode, "control_queue": session.control_queue or [],
        "stream_room_name": session.stream_room_name,
        "started_at": session.started_at, "last_activity_at": session.last_activity_at,
        "error_message": session.error_message,
    }


@router.get("/entries", response_model=list[BrowserEntryView])
def entries(
    q: str = Query(default="", max_length=100), category: str | None = None,
    entry_type: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    query = select(BrowserEntry).where(
        BrowserEntry.enabled.is_(True),
        or_(BrowserEntry.expires_at.is_(None), BrowserEntry.expires_at > now),
    )
    if q:
        term = f"%{q.strip()}%"
        query = query.where(or_(BrowserEntry.name.ilike(term), BrowserEntry.category.ilike(term), BrowserEntry.description.ilike(term), BrowserEntry.entry_type.ilike(term)))
    if category:
        query = query.where(BrowserEntry.category == category)
    if entry_type:
        query = query.where(BrowserEntry.entry_type == entry_type)
    return db.scalars(query.order_by(BrowserEntry.pinned.desc(), BrowserEntry.featured.desc(), BrowserEntry.sort_order, BrowserEntry.name)).all()


@router.get("/entries/{entry_id}", response_model=BrowserEntryView)
def entry(entry_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.get(BrowserEntry, entry_id)
    if not row or not row.enabled:
        raise HTTPException(status_code=404, detail="Entrada nao encontrada")
    return row


@router.get("/status")
async def browser_status():
    status = await browser_service.status()
    configured = livekit_configured()
    livekit = await livekit_health()
    publisher_ready = status.get("publisher") == "healthy"
    sfu_ready = livekit["status"] == "healthy"
    return {**status, "state_store": browser_state_store.backend, "livekit": livekit,
            "webrtc": "healthy" if configured and sfu_ready and publisher_ready else "unavailable",
            "sfu": "healthy" if sfu_ready else livekit["status"]}


@router.get("/capabilities")
def browser_capabilities(room_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    room = db.get(Room, room_id)
    if not room: raise HTTPException(status_code=404, detail="Sala nao encontrada")
    session = db.scalar(select(BrowserSession).where(BrowserSession.room_id == room_id, BrowserSession.closed_at.is_(None)))
    host = is_host(db, room, user) or bool(session and session.host_user_id == user.id)
    control = host or bool(session and may_control(session, room, user))
    return {"is_host": host, "can_control": control, "can_navigate": control, "can_open_manual_url": host and bool(browser_setting("manual_url", get_settings().browser_manual_url_enabled))}


@router.get("/rooms")
def browser_rooms(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(BrowserSession).where(BrowserSession.closed_at.is_(None)).order_by(BrowserSession.started_at.desc())).all()
    return [serialize_session(db, row) for row in rows]


@router.get("/session")
def get_session(room_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(BrowserSession).where(BrowserSession.room_id == room_id, BrowserSession.closed_at.is_(None)))
    if not row:
        raise HTTPException(status_code=404, detail="Sessao de navegador nao encontrada")
    return serialize_session(db, row)


@router.post("/session/start")
async def start_session(payload: BrowserSessionStart, user: User = Depends(current_user), db: Session = Depends(get_db)):
    room = db.get(Room, payload.room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Sala nao encontrada")
    entry = db.get(BrowserEntry, payload.entry_id) if payload.entry_id else None
    if payload.entry_id and (not entry or not entry.enabled):
        raise HTTPException(status_code=404, detail="Entrada nao encontrada")
    stored = db.scalar(select(BrowserSession).where(BrowserSession.room_id == room.id))
    existing = stored if stored and stored.closed_at is None else None
    has_control = is_host(db, room, user) or bool(existing and (existing.host_user_id == user.id or may_control(existing, room, user)))
    if not has_control:
        raise HTTPException(status_code=403, detail="Voce nao possui controle do navegador")
    if payload.url and not is_host(db, room, user) and not (existing and existing.host_user_id == user.id):
        raise HTTPException(status_code=403, detail="Somente o host pode abrir um endereco livre")
    if payload.url and not bool(browser_setting("manual_url", get_settings().browser_manual_url_enabled)):
        raise HTTPException(status_code=403, detail="Abertura manual de URLs esta desativada")
    url = payload.url or (entry.url if entry else None)
    if not url:
        raise HTTPException(status_code=422, detail="Informe uma entrada ou URL")
    try:
        await validate_public_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    row = stored
    try:
        control_setting = db.get(BrowserSetting, "control_mode")
        default_control = control_setting.value if control_setting and control_setting.value in {"HOST_ONLY", "REQUEST_CONTROL", "SHARED"} else "REQUEST_CONTROL"
        shield_mode = payload.shield_mode or (entry.shield_mode if entry else (row.shield_mode if row else browser_setting("shield_mode", "STANDARD")))
        if not row:
            row = BrowserSession(
                room_id=room.id,
                host_user_id=room.host_user_id or user.id,
                current_url=url,
                current_entry_id=entry.id if entry else None,
                shield_mode=shield_mode,
                stream_room_name=f"craftplay-{room.id}",
                control_mode=default_control,
            )
            db.add(row)
        else:
            # BrowserSession.room_id is unique. Closed sessions must be reopened
            # in place instead of inserting a second row for the same room.
            row.host_user_id = room.host_user_id or user.id
            row.current_url = url
            row.current_entry_id = entry.id if entry else None
            row.shield_mode = shield_mode
            row.stream_room_name = f"craftplay-{room.id}"
            row.control_mode = default_control
            row.controller_user_id = None
            row.control_expires_at = None
            row.control_queue = []
            row.privacy_mode = False
            row.session_locked = False
            row.closed_at = None
            row.started_at = datetime.now(timezone.utc)
        row.browser_status = "STARTING"
        row.error_message = None
        row.last_activity_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Falha ao preparar sessao do navegador para a sala %s", room.id)
        raise HTTPException(status_code=503, detail="Nao foi possivel preparar a sessao no banco de dados") from exc

    try:
        runtime = await browser_service.start(room.id, row.id, url, row.shield_mode)
        row.current_url, row.browser_status, row.last_activity_at = runtime.current_url, "READY", datetime.now(timezone.utc)
        if entry:
            db.add(BrowserHistory(user_id=user.id, entry_id=entry.id, room_id=room.id))
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Falha ao iniciar Chromium para a sala %s", room.id)
        failed_row = db.get(BrowserSession, row.id)
        if failed_row:
            failed_row.browser_status, failed_row.error_message = "ERROR", str(exc)[:500]
            try:
                db.commit()
            except SQLAlchemyError:
                db.rollback()
                logger.exception("Falha ao registrar erro da sessao do navegador %s", row.id)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return serialize_session(db, row)


@router.post("/session/navigate")
async def navigate(payload: BrowserNavigate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    room = db.get(Room, payload.room_id)
    row = db.scalar(select(BrowserSession).where(BrowserSession.room_id == payload.room_id, BrowserSession.closed_at.is_(None)))
    if not room or not row:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada")
    if not may_control(row, room, user):
        raise HTTPException(status_code=403, detail="Voce nao possui controle do navegador")
    if row.privacy_mode and row.host_user_id != user.id:
        raise HTTPException(status_code=423, detail="O host esta realizando uma acao privada")
    try:
        row.current_url = await browser_service.navigate(payload.room_id, payload.url)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row.last_activity_at = datetime.now(timezone.utc)
    db.commit()
    return serialize_session(db, row)


@router.post("/session/action")
async def session_action(payload: BrowserInputCommand, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """HTTP input fallback for environments that interrupt room WebSockets."""
    room = db.get(Room, payload.room_id)
    row = db.scalar(select(BrowserSession).where(BrowserSession.room_id == payload.room_id, BrowserSession.closed_at.is_(None)))
    if not room or not row:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada")
    if not may_control(row, room, user):
        raise HTTPException(status_code=403, detail="Voce nao possui controle do navegador")
    if row.privacy_mode and row.host_user_id != user.id:
        raise HTTPException(status_code=423, detail="O host esta realizando uma acao privada")
    try:
        row.current_url = await browser_service.action(payload.room_id, payload.event, payload.model_dump(exclude={"room_id", "event"}))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row.last_activity_at = datetime.now(timezone.utc)
    db.commit()
    return serialize_session(db, row)


@router.post("/session/close", status_code=204)
async def close_session(payload: BrowserSessionAction, user: User = Depends(current_user), db: Session = Depends(get_db)):
    room = db.get(Room, payload.room_id)
    row = db.scalar(select(BrowserSession).where(BrowserSession.room_id == payload.room_id, BrowserSession.closed_at.is_(None)))
    if not room or not row:
        return Response(status_code=204)
    if not is_host(db, room, user) and row.host_user_id != user.id:
        raise HTTPException(status_code=403, detail="Somente o host pode encerrar a sessao")
    await browser_service.close(payload.room_id, preserve_profile=row.profile_mode == "PERSISTENT")
    await browser_state_store.delete(payload.room_id)
    row.browser_status, row.closed_at = "CLOSED", datetime.now(timezone.utc)
    db.commit()
    return Response(status_code=204)


@router.get("/session/token")
def session_token(room_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(BrowserSession).where(BrowserSession.room_id == room_id, BrowserSession.closed_at.is_(None)))
    if not row:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada")
    if row.privacy_mode and row.host_user_id != user.id:
        raise HTTPException(status_code=423, detail="O host esta realizando uma acao privada")
    try:
        token = create_viewer_token(row.stream_room_name, user.discord_id, user.username)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"url": get_settings().livekit_url, "token": token, "room": row.stream_room_name}


@router.get("/session/frame")
async def session_frame(room_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Authenticated JPEG fallback for hosts where WebSockets are interrupted."""
    row = db.scalar(select(BrowserSession).where(BrowserSession.room_id == room_id, BrowserSession.closed_at.is_(None)))
    if not row:
        raise HTTPException(status_code=404, detail="Sessao de navegador nao encontrada")
    if row.privacy_mode and row.host_user_id != user.id:
        raise HTTPException(status_code=423, detail="O host esta realizando uma acao privada")
    try:
        image = await browser_service.capture_frame_bytes(room_id)
    except Exception as exc:
        logger.exception("Falha ao capturar frame HTTP da sala %s", room_id)
        raise HTTPException(status_code=503, detail=f"Captura do navegador indisponivel: {type(exc).__name__}") from exc
    return Response(
        content=image,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store, max-age=0", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/session/stream")
async def session_stream(room_id: str, authorization: str = Header(default="")):
    """Single authenticated NDJSON stream for high-frame-rate fallback."""
    ticket = authorization[7:] if authorization.startswith("Bearer ") else ""
    try:
        identity = decode_websocket_ticket(ticket, room_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Ticket de transmissao invalido") from exc
    discord_id = str(identity["sub"])
    with SessionLocal() as db:
        row = db.scalar(select(BrowserSession).where(BrowserSession.room_id == room_id, BrowserSession.closed_at.is_(None)))
        user = db.scalar(select(User).where(User.discord_id == discord_id))
        if not row or not user:
            raise HTTPException(status_code=404, detail="Sessao de navegador nao encontrada")

    async def frames():
        last_sequence = -1
        privacy_check_at = 0.0
        may_watch = True
        interval = 1 / 30
        while True:
            now = time.monotonic()
            if now >= privacy_check_at:
                with SessionLocal() as check_db:
                    active = check_db.scalar(select(BrowserSession).where(BrowserSession.room_id == room_id, BrowserSession.closed_at.is_(None)))
                    may_watch = bool(active and (not active.privacy_mode or active.host_user_id == user.id))
                if not active:
                    return
                privacy_check_at = now + 1
            try:
                sequence, encoded = browser_service.latest_frame(room_id)
            except RuntimeError:
                return
            if may_watch and encoded and sequence != last_sequence:
                last_sequence = sequence
                yield f'{{"sequence":{sequence},"mime":"image/jpeg","data":"{encoded}"}}\n'.encode()
            await asyncio.sleep(interval)

    return StreamingResponse(
        frames(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "private, no-cache, no-store, max-age=0",
            "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/favorites")
def browser_favorites(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(BrowserEntry).join(BrowserFavorite, BrowserFavorite.entry_id == BrowserEntry.id).where(BrowserFavorite.user_id == user.id)).all()


@router.post("/favorites/{entry_id}", status_code=201)
def add_browser_favorite(entry_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not db.get(BrowserEntry, entry_id):
        raise HTTPException(status_code=404, detail="Entrada nao encontrada")
    row = db.scalar(select(BrowserFavorite).where(BrowserFavorite.user_id == user.id, BrowserFavorite.entry_id == entry_id))
    if not row:
        row = BrowserFavorite(user_id=user.id, entry_id=entry_id)
        db.add(row); db.commit()
    return {"saved": True}


@router.delete("/favorites/{entry_id}", status_code=204)
def remove_browser_favorite(entry_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(delete(BrowserFavorite).where(BrowserFavorite.user_id == user.id, BrowserFavorite.entry_id == entry_id)); db.commit()
    return Response(status_code=204)


@dashboard_router.get("/entries", response_model=list[BrowserEntryView])
def dashboard_entries(admin: User = Depends(current_dashboard_admin), db: Session = Depends(get_db)):
    return db.scalars(select(BrowserEntry).order_by(BrowserEntry.sort_order, BrowserEntry.name)).all()


@dashboard_router.post("/entries", response_model=BrowserEntryView, status_code=201)
async def create_entry(payload: BrowserEntryCreate, admin: User = Depends(current_dashboard_admin), db: Session = Depends(get_db)):
    await validate_public_url(payload.url)
    if payload.open_mode == "direct":
        source_type = "hls" if ".m3u8" in payload.url else "dash" if ".mpd" in payload.url else "webm" if ".webm" in payload.url else "mp4"
        valid, reason = await validate_media_url(payload.url, source_type)
        if not valid: raise HTTPException(status_code=422, detail=f"Midia direta recusada: {reason}")
    data = payload.model_dump()
    data["slug"] = unique_slug(db, payload.slug or slugify(payload.name))
    row = BrowserEntry(**data, created_by=admin.id)
    db.add(row); db.flush(); audit(db, admin, "ENTRY_CREATE", "BrowserEntry", row.id); db.commit(); db.refresh(row)
    return row


@dashboard_router.patch("/entries/{entry_id}", response_model=BrowserEntryView)
async def update_entry(entry_id: int, payload: BrowserEntryUpdate, admin: User = Depends(current_dashboard_admin), db: Session = Depends(get_db)):
    row = db.get(BrowserEntry, entry_id)
    if not row:
        raise HTTPException(status_code=404, detail="Entrada nao encontrada")
    data = payload.model_dump(exclude_unset=True)
    if "url" in data:
        await validate_public_url(data["url"])
    next_mode = data.get("open_mode", row.open_mode)
    next_url = data.get("url", row.url)
    if next_mode == "direct" and ({"url", "open_mode"} & set(data)):
        source_type = "hls" if ".m3u8" in next_url else "dash" if ".mpd" in next_url else "webm" if ".webm" in next_url else "mp4"
        valid, reason = await validate_media_url(next_url, source_type)
        if not valid: raise HTTPException(status_code=422, detail=f"Midia direta recusada: {reason}")
    if "slug" in data:
        data["slug"] = unique_slug(db, data["slug"] or slugify(data.get("name", row.name)), row.id)
    for key, value in data.items(): setattr(row, key, value)
    row.updated_at = datetime.now(timezone.utc); audit(db, admin, "ENTRY_UPDATE", "BrowserEntry", row.id, {"fields": sorted(data)}); db.commit(); db.refresh(row)
    return row


@dashboard_router.delete("/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: int, admin: User = Depends(current_dashboard_admin), db: Session = Depends(get_db)):
    row = db.get(BrowserEntry, entry_id)
    if row:
        audit(db, admin, "ENTRY_DELETE", "BrowserEntry", row.id); db.delete(row); db.commit()
    return Response(status_code=204)


@dashboard_router.post("/entries/{entry_id}/duplicate", response_model=BrowserEntryView, status_code=201)
def duplicate_entry(entry_id: int, admin: User = Depends(current_dashboard_admin), db: Session = Depends(get_db)):
    row = db.get(BrowserEntry, entry_id)
    if not row:
        raise HTTPException(status_code=404, detail="Entrada nao encontrada")
    fields = {column.name: getattr(row, column.name) for column in BrowserEntry.__table__.columns if column.name not in {"id", "slug", "created_at", "updated_at", "created_by"}}
    copy = BrowserEntry(**fields, name=f"{row.name} (copia)", slug=unique_slug(db, f"{row.slug}-copia"), created_by=admin.id)
    db.add(copy); db.flush(); audit(db, admin, "ENTRY_DUPLICATE", "BrowserEntry", copy.id, {"source_id": row.id}); db.commit(); db.refresh(copy)
    return copy


@dashboard_router.post("/test")
async def test_link(payload: BrowserTestRequest, admin: User = Depends(current_dashboard_admin)):
    safe = await validate_public_url(payload.url)
    started, redirects, current = time.monotonic(), [], safe.url
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"User-Agent": "CraftPlay-Link-Test/1.0"}) as client:
        for _ in range(5):
            response = await client.get(current)
            if response.is_redirect:
                target = urljoin(current, response.headers.get("location", ""))
                await validate_public_url(target)
                redirects.append({"from": current, "to": target, "status": response.status_code})
                current = target
                continue
            break
    return {"accessible": response.is_success, "https": safe.url.startswith("https://"), "status": response.status_code,
            "load_seconds": round(time.monotonic() - started, 3), "final_url": current, "redirects": redirects,
            "popups_blocked": 0, "downloads_detected": 0, "note": "Teste HTTP seguro; compatibilidade visual exige uma sessao Chromium ativa."}


@dashboard_router.get("/rooms")
def dashboard_rooms(admin: User = Depends(current_dashboard_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(BrowserSession).where(BrowserSession.closed_at.is_(None)).order_by(BrowserSession.started_at.desc())).all()
    return [serialize_session(db, row) for row in rows]


@dashboard_router.post("/open-now")
async def dashboard_open_now(payload: BrowserNavigate, admin: User = Depends(current_dashboard_admin), db: Session = Depends(get_db)):
    row = db.scalar(select(BrowserSession).where(BrowserSession.room_id == payload.room_id, BrowserSession.closed_at.is_(None)))
    if not row:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada")
    await validate_public_url(payload.url, enforce_allowlist=row.shield_mode == "STRICT")
    try:
        row.current_url = await browser_service.navigate(payload.room_id, payload.url)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    row.last_activity_at = datetime.now(timezone.utc)
    audit(db, admin, "OPEN_NOW", "BrowserSession", row.id, {"host": __import__("urllib.parse", fromlist=["urlparse"]).urlparse(payload.url).hostname})
    db.commit()
    return serialize_session(db, row)


@dashboard_router.post("/rooms/{room_id}/close", status_code=204)
async def dashboard_close_room(room_id: str, admin: User = Depends(current_dashboard_admin), db: Session = Depends(get_db)):
    row = db.scalar(select(BrowserSession).where(BrowserSession.room_id == room_id, BrowserSession.closed_at.is_(None)))
    if row:
        await browser_service.close(room_id)
        await browser_state_store.delete(room_id)
        row.browser_status, row.closed_at = "CLOSED", datetime.now(timezone.utc)
        audit(db, admin, "SESSION_CLOSE", "BrowserSession", row.id); db.commit()
    return Response(status_code=204)


@dashboard_router.post("/rooms/{room_id}/revoke-control")
def dashboard_revoke_control(room_id: str, admin: User = Depends(current_dashboard_admin), db: Session = Depends(get_db)):
    row = db.scalar(select(BrowserSession).where(BrowserSession.room_id == room_id, BrowserSession.closed_at.is_(None)))
    if not row: raise HTTPException(status_code=404, detail="Sessao nao encontrada")
    row.controller_user_id = None; row.control_expires_at = None
    audit(db, admin, "CONTROL_REVOKE", "BrowserSession", row.id); db.commit()
    return serialize_session(db, row)


@dashboard_router.post("/rooms/{room_id}/home")
async def dashboard_room_home(room_id: str, admin: User = Depends(current_dashboard_admin), db: Session = Depends(get_db)):
    row = db.scalar(select(BrowserSession).where(BrowserSession.room_id == room_id, BrowserSession.closed_at.is_(None)))
    if not row: raise HTTPException(status_code=404, detail="Sessao nao encontrada")
    await browser_service.action(room_id, "HOME", {})
    row.current_url = browser_setting("homepage", get_settings().browser_homepage)
    audit(db, admin, "SESSION_HOME", "BrowserSession", row.id); db.commit()
    return serialize_session(db, row)


@dashboard_router.get("/tmdb/search")
async def dashboard_tmdb_search(q: str = Query(min_length=2, max_length=100), admin: User = Depends(current_dashboard_admin)):
    return {"items": await catalog.search(q, 1)}


@dashboard_router.get("/settings")
def browser_settings(admin: User = Depends(current_dashboard_admin), db: Session = Depends(get_db)):
    configured = {row.key: row.value for row in db.scalars(select(BrowserSetting)).all()}
    settings = get_settings()
    return {"control_mode": configured.get("control_mode", "REQUEST_CONTROL"), "shield_mode": configured.get("shield_mode", "STANDARD"),
            "idle_timeout": configured.get("idle_timeout", settings.browser_idle_timeout), "max_participants": configured.get("max_participants", settings.room_max_participants),
            "homepage": configured.get("homepage", settings.browser_homepage), "allow_downloads": settings.browser_allow_downloads,
            "manual_url": configured.get("manual_url", settings.browser_manual_url_enabled)}


@dashboard_router.patch("/settings")
async def update_browser_settings(payload: dict, admin: User = Depends(current_dashboard_admin), db: Session = Depends(get_db)):
    allowed = {"control_mode", "shield_mode", "idle_timeout", "max_participants", "homepage", "manual_url", "privacy_on_password"}
    if "control_mode" in payload and payload["control_mode"] not in {"HOST_ONLY", "REQUEST_CONTROL", "SHARED"}: raise HTTPException(status_code=422, detail="Control mode invalido")
    if "shield_mode" in payload and payload["shield_mode"] not in {"OFF", "STANDARD", "STRICT"}: raise HTTPException(status_code=422, detail="Shield mode invalido")
    if "idle_timeout" in payload and not 60 <= int(payload["idle_timeout"]) <= 86400: raise HTTPException(status_code=422, detail="Idle timeout invalido")
    if "max_participants" in payload and not 1 <= int(payload["max_participants"]) <= 50: raise HTTPException(status_code=422, detail="Limite de participantes invalido")
    if payload.get("homepage") and payload["homepage"] != "about:blank": await validate_public_url(str(payload["homepage"]))
    for key, value in payload.items():
        if key not in allowed: continue
        row = db.get(BrowserSetting, key)
        if not row: row = BrowserSetting(key=key); db.add(row)
        row.value = value; row.updated_by = admin.id
    audit(db, admin, "SETTINGS_UPDATE", "BrowserSetting", details={"fields": sorted(set(payload) & allowed)}); db.commit()
    return browser_settings(admin, db)


@dashboard_router.get("/domains")
def domains(admin: User = Depends(current_dashboard_admin), db: Session = Depends(get_db)):
    return {"blocked": db.scalars(select(BlockedDomain).order_by(BlockedDomain.domain)).all(), "allowed": db.scalars(select(AllowedDomain).order_by(AllowedDomain.domain)).all()}


@dashboard_router.post("/domains/blocked", status_code=201)
def block_domain(payload: dict, admin: User = Depends(current_dashboard_admin), db: Session = Depends(get_db)):
    domain = str(payload.get("domain", "")).strip().casefold().lstrip("*.")
    if not domain or "/" in domain: raise HTTPException(status_code=422, detail="Dominio invalido")
    row = db.scalar(select(BlockedDomain).where(BlockedDomain.domain == domain)) or BlockedDomain(domain=domain, created_by=admin.id)
    row.reason = str(payload.get("reason", ""))[:500]; db.add(row); audit(db, admin, "DOMAIN_BLOCK", "BlockedDomain", domain); db.commit(); db.refresh(row); return row


@dashboard_router.delete("/domains/blocked/{domain}", status_code=204)
def unblock_domain(domain: str, admin: User = Depends(current_dashboard_admin), db: Session = Depends(get_db)):
    db.execute(delete(BlockedDomain).where(BlockedDomain.domain == domain.casefold())); audit(db, admin, "DOMAIN_UNBLOCK", "BlockedDomain", domain); db.commit(); return Response(status_code=204)


@dashboard_router.get("/overview")
async def overview(admin: User = Depends(current_dashboard_admin), db: Session = Depends(get_db)):
    status = await browser_service.status()
    return {"entries": db.scalar(select(func.count()).select_from(BrowserEntry)) or 0,
            "active_rooms": db.scalar(select(func.count()).select_from(BrowserSession).where(BrowserSession.closed_at.is_(None))) or 0,
            "connected_users": sum(len(items) for items in __import__("backend.room_manager", fromlist=["room_manager"]).room_manager.connections.values()),
            "browser": status, "webrtc": "configured" if livekit_configured() else "unavailable"}


@dashboard_router.get("/debug/{room_id}")
def debug_browser(room_id: str, admin: User = Depends(current_dashboard_admin)):
    try:
        return browser_service.debug(room_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
