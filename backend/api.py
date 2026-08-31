import os
import secrets
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth import create_access_token, create_websocket_ticket, current_user, exchange_discord_code, upsert_user
from backend.config import get_settings
from backend.database import database_status, get_db
from backend.models import CustomSource, Favorite, Room, RoomMember, User, WatchHistory
from backend.playback import PlaybackResolver
from backend.playback.validation import validate_media_url
from backend.providers import CatalogService
from backend.providers.watch_availability import WatchAvailabilityProvider
from backend.schemas import CustomSourceCreate, DiscordAuthRequest, ExternalIds, FavoriteCreate, MediaItem, ProgressCreate, ProviderDebugRequest, RoomCreate, RoomView, SourceFailureRequest, SourceValidationRequest


router = APIRouter(prefix="/api")
catalog = CatalogService()
playback = PlaybackResolver()
availability = WatchAvailabilityProvider()
APP_RELEASE = "2026.08.30.7"


def require_admin(x_admin_key: str = Header(default="")):
    expected = get_settings().admin_api_key
    if not expected:
        raise HTTPException(status_code=503, detail="ADMIN_API_KEY nao configurada")
    if not secrets.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=401, detail="Chave administrativa invalida")


@router.get("/health")
def health():
    settings = get_settings()
    return {
        "status": "ok", "service": "craftplay",
        "release": os.getenv("GIT_COMMIT_SHA") or os.getenv("SOURCE_VERSION") or APP_RELEASE,
        "playback_validation_version": 3,
        "database": database_status(),
        "configuration": {
            "discord_client": bool(settings.discord_client_id),
            "discord_oauth": bool(settings.discord_client_id and settings.discord_client_secret),
            "dashboard_user_allowlist": bool(settings.dashboard_allowed_user_ids),
            "tmdb": bool(settings.tmdb_api_key or settings.tmdb_read_access_token),
            "environment": settings.environment,
        },
    }


@router.get("/config")
def public_config():
    settings = get_settings()
    return {
        "discord_client_id": settings.discord_client_id,
        "activity_url": settings.discord_activity_url,
        "environment": settings.environment,
        "discord_configured": bool(settings.discord_client_id and settings.discord_client_secret),
        "tmdb_configured": bool(settings.tmdb_api_key or settings.tmdb_read_access_token),
        "plenoflu_enabled": settings.plenoflu_enabled,
        "redecanais_provider_enabled": settings.redecanais_provider_enabled,
        "jw_player": {
            "enabled": settings.jw_player_enabled,
            "library_url": settings.jw_player_library_url,
            "license_key": settings.jw_player_license_key,
        },
        "browser": {
            "default_mode": "REQUEST_CONTROL",
            "max_participants": settings.room_max_participants,
            "manual_url_enabled": settings.browser_manual_url_enabled,
            "livekit_configured": bool(settings.livekit_url and settings.livekit_api_key and settings.livekit_api_secret),
        },
    }


@router.post("/discord/interactions")
async def discord_interactions(
    request: Request,
    x_signature_ed25519: str = Header(default=""),
    x_signature_timestamp: str = Header(default=""),
):
    """Receives Discord interactions and launches the Activity for /iniciar-player."""
    settings = get_settings()
    if not settings.discord_public_key:
        raise HTTPException(status_code=503, detail="Chave pública do Discord não configurada")
    body = await request.body()
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(settings.discord_public_key))
        key.verify(bytes.fromhex(x_signature_ed25519), x_signature_timestamp.encode() + body)
    except (ValueError, InvalidSignature) as exc:
        raise HTTPException(status_code=401, detail="Assinatura do Discord inválida") from exc
    payload = await request.json()
    if payload.get("type") == 1:
        return {"type": 1}
    if payload.get("type") == 2 and payload.get("data", {}).get("name") == "iniciar-player":
        return {"type": 12}
    return {"type": 4, "data": {"content": "Comando não reconhecido.", "flags": 64}}


@router.post("/auth/discord")
async def discord_auth(payload: DiscordAuthRequest, db: Session = Depends(get_db)):
    oauth = await exchange_discord_code(payload.code)
    profile = oauth["profile"]
    avatar = f"https://cdn.discordapp.com/avatars/{profile['id']}/{profile['avatar']}.png" if profile.get("avatar") else None
    user = upsert_user(db, profile["id"], profile.get("global_name") or profile["username"], avatar)
    return {"access_token": create_access_token(user), "discord_access_token": oauth["access_token"], "user": {"discord_id": user.discord_id, "username": user.username, "avatar": user.avatar}}


@router.post("/auth/dashboard")
def dashboard_auth(user: User = Depends(current_user)):
    """Promote an authenticated Activity user explicitly listed by Discord ID."""
    settings = get_settings()
    if user.discord_id not in settings.dashboard_allowed_user_ids:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Acesso negado para o Discord ID {user.discord_id}. "
                f"Configure DASHBOARD_ALLOWED_USER_IDS={user.discord_id} e reinicie o servico."
            ),
        )
    return {
        "access_token": create_access_token(user, dashboard_admin=True),
        "user": {"discord_id": user.discord_id, "username": user.username, "avatar": user.avatar},
    }


@router.get("/home")
async def home(user: User = Depends(current_user)):
    sections = await catalog.home()
    return {"sections": sections, "providers": catalog.status(), "user": {"discord_id": user.discord_id, "username": user.username, "avatar": user.avatar}}


@router.get("/search")
async def search(
    q: str = Query(default="", max_length=100), media_type: str | None = None,
    year: int | None = None, genre: str | None = None, rating: float | None = None,
    sort: str = "popularity", page: int = Query(default=1, ge=1, le=100),
    user: User = Depends(current_user),
):
    items = await catalog.search(q, page) if q else sum((await catalog.home()).values(), [])
    unique = {item.id: item for item in items}.values()
    filtered = [item for item in unique if (not media_type or item.media_type == media_type) and (not year or item.year == year) and (not genre or genre.casefold() in [g.casefold() for g in item.genres]) and (rating is None or item.rating >= rating)]
    key = (lambda item: item.rating) if sort == "rating" else (lambda item: item.year or 0) if sort == "year" else (lambda item: item.popularity)
    return {"items": sorted(filtered, key=key, reverse=True)[:24], "page": page, "count": len(filtered)}


@router.get("/media/{media_id:path}/recommendations")
async def recommendations(media_id: str, user: User = Depends(current_user)):
    return {"items": await catalog.recommendations(media_id)}


@router.get("/media/{media_id:path}/sources")
async def sources(media_id: str, season: int = 0, episode: int = 0,
                  exclude_provider: list[str] = Query(default=[]), user: User = Depends(current_user)):
    item = await catalog.details(media_id)
    if not item:
        raise HTTPException(status_code=404, detail="Conteúdo não encontrado")
    resolved = await playback.resolve(item, season, episode, exclude_providers=set(exclude_provider))
    unavailable = []
    settings = get_settings()
    if settings.plenoflu_enabled and item.external_ids.imdb and not any(source.provider == "plenoflu" for source in resolved):
        unavailable.append({
            "provider_name": "PlenoFlu",
            "message": "O PlenoFlu recusou a incorporação deste conteúdo. A proteção do serviço foi respeitada e nenhuma tentativa de contorno foi realizada.",
        })
    return {"sources": resolved, "unavailable": unavailable}


@router.post("/playback/source-failure")
def playback_source_failure(payload: SourceFailureRequest, user: User = Depends(current_user)):
    playback.invalidate(payload.media_id)
    return {"invalidated": True, "provider": payload.provider}


@router.get("/media/{media_id:path}/availability")
async def media_availability(media_id: str, user: User = Depends(current_user)):
    item = await catalog.details(media_id)
    if not item:
        raise HTTPException(status_code=404, detail="Conteudo nao encontrado")
    try:
        return await availability.get(item)
    except Exception as exc:
        return {"provider": "tmdb", "region": "BR", "items": [], "error": f"{type(exc).__name__}: {exc}"}


@router.get("/playback/providers/status")
async def provider_status():
    return {"providers": await playback.status()}


@router.post("/playback/debug")
async def provider_debug(payload: ProviderDebugRequest, _: None = Depends(require_admin)):
    media = MediaItem(id="debug:query", title=payload.title, original_title=payload.title,
                      media_type=payload.media_type, year=payload.year, external_ids=ExternalIds())
    return {"query": payload.model_dump(), "providers": await playback.debug(media, payload.season, payload.episode)}


@router.get("/playback/test-sources")
async def test_sources(_: None = Depends(require_admin)):
    candidates = [
        {"provider": "Blender Open Movie / Internet Archive", "type": "mp4", "url": "https://archive.org/download/youtube-aqz-KE-bpKQ/aqz-KE-bpKQ.mp4", "media_id": "test:mp4", "quality": "720p", "language": "original"},
        {"provider": "Mux test stream", "type": "hls", "url": "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8", "media_id": "test:hls", "quality": "auto", "language": "original"},
        {"provider": "Shaka demo assets", "type": "dash", "url": "https://storage.googleapis.com/shaka-demo-assets/angel-one/dash.mpd", "media_id": "test:dash", "quality": "auto", "language": "original"},
        {"provider": "YouTube API demo", "type": "youtube", "url": "https://www.youtube.com/embed/M7lc1UVf-VE?enablejsapi=1", "media_id": "test:youtube", "quality": "auto", "language": "original", "metadata": {"video_id": "M7lc1UVf-VE"}},
        {"provider": "Vimeo SDK demo", "type": "vimeo", "url": "https://player.vimeo.com/video/59777392", "media_id": "test:vimeo", "quality": "auto", "language": "original", "metadata": {"video_id": "59777392"}},
    ]
    results = []
    for candidate in candidates:
        valid, reason = await validate_media_url(candidate["url"], candidate["type"])
        results.append({**candidate, "is_playable": valid, "validation": reason})
    return {"sources": results}


@router.post("/playback/validate-source")
async def validate_debug_source(payload: SourceValidationRequest, _: None = Depends(require_admin)):
    valid, reason = await validate_media_url(payload.url, payload.source_type)
    return {"source": {"provider": payload.provider, "type": payload.source_type, "url": payload.url,
                       "media_id": "debug:player", "quality": payload.quality, "language": "original",
                       "subtitles": [], "audio_tracks": [], "is_playable": valid,
                       "metadata": {"validation": reason}}, "validation": reason}


@router.get("/admin/sources")
def list_custom_sources(_: None = Depends(require_admin), db: Session = Depends(get_db)):
    return {"items": db.scalars(select(CustomSource).order_by(CustomSource.created_at.desc())).all()}


@router.post("/admin/sources", status_code=201)
async def create_custom_source(payload: CustomSourceCreate, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    valid, reason = await validate_media_url(payload.url, payload.source_type)
    if not valid:
        raise HTTPException(status_code=422, detail=f"Fonte recusada: {reason}")
    row = CustomSource(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    playback.invalidate(payload.media_id)
    return row


@router.patch("/admin/sources/{source_id}")
def toggle_custom_source(source_id: int, enabled: bool, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.get(CustomSource, source_id)
    if not row:
        raise HTTPException(status_code=404, detail="Fonte nao encontrada")
    row.enabled = enabled
    db.commit()
    playback.invalidate(row.media_id)
    return row


@router.delete("/admin/sources/{source_id}", status_code=204)
def delete_custom_source(source_id: int, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.get(CustomSource, source_id)
    if row:
        media_id = row.media_id
        db.delete(row)
        db.commit()
        playback.invalidate(media_id)
    return Response(status_code=204)


@router.get("/media/{media_id:path}")
async def media(media_id: str, user: User = Depends(current_user)):
    item = await catalog.details(media_id)
    if not item:
        raise HTTPException(status_code=404, detail="Conteúdo não encontrado")
    return item


@router.get("/movie/{media_id:path}")
@router.get("/tv/{media_id:path}")
@router.get("/anime/{media_id:path}")
async def typed_media(media_id: str, user: User = Depends(current_user)):
    return await media(media_id, user)


@router.get("/user/history")
def history(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"items": db.scalars(select(WatchHistory).where(WatchHistory.user_id == user.id).order_by(WatchHistory.updated_at.desc())).all()}


@router.post("/playback/progress")
def save_progress(payload: ProgressCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    entry = db.scalar(select(WatchHistory).where(WatchHistory.user_id == user.id, WatchHistory.media_id == payload.media_id, WatchHistory.season == payload.season, WatchHistory.episode == payload.episode))
    if not entry:
        entry = WatchHistory(user_id=user.id, media_id=payload.media_id, media_type=payload.media_type, season=payload.season, episode=payload.episode)
        db.add(entry)
    entry.position, entry.duration, entry.updated_at = payload.position, payload.duration, datetime.now(timezone.utc)
    db.commit()
    return {"saved": True}


@router.get("/user/favorites")
def favorites(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"items": db.scalars(select(Favorite).where(Favorite.user_id == user.id).order_by(Favorite.created_at.desc())).all()}


@router.post("/user/favorites", status_code=201)
def add_favorite(payload: FavoriteCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    favorite = db.scalar(select(Favorite).where(Favorite.user_id == user.id, Favorite.media_id == payload.media_id, Favorite.media_type == payload.media_type))
    if not favorite:
        favorite = Favorite(user_id=user.id, media_id=payload.media_id, media_type=payload.media_type)
        db.add(favorite)
        try:
            db.commit()
            db.refresh(favorite)
        except IntegrityError:
            db.rollback()
            favorite = db.scalar(select(Favorite).where(Favorite.user_id == user.id, Favorite.media_id == payload.media_id, Favorite.media_type == payload.media_type))
    return favorite


@router.delete("/user/favorites/{media_id:path}", status_code=204)
def remove_favorite(media_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(delete(Favorite).where(Favorite.user_id == user.id, Favorite.media_id == media_id))
    db.commit()
    return Response(status_code=204)


@router.post("/rooms", response_model=RoomView)
def create_room(payload: RoomCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    room = db.scalar(select(Room).where(Room.discord_instance_id == payload.discord_instance_id))
    if not room:
        room = Room(discord_instance_id=payload.discord_instance_id, host_user_id=user.id)
        db.add(room)
        db.flush()
        db.add(RoomMember(room_id=room.id, user_id=user.id))
        db.commit()
        db.refresh(room)
    elif room.host_user_id is None:
        room.host_user_id = user.id
        db.commit()
        db.refresh(room)
    return room


@router.get("/rooms/{room_id}", response_model=RoomView)
def get_room(room_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    room = db.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")
    return room


@router.post("/rooms/{room_id}/ticket")
def room_websocket_ticket(room_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not db.get(Room, room_id):
        raise HTTPException(status_code=404, detail="Sala nao encontrada")
    return {"ticket": create_websocket_ticket(user, room_id)}
