from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.auth import create_access_token, current_user, exchange_discord_code, upsert_user
from backend.config import get_settings
from backend.database import get_db
from backend.models import Favorite, Room, RoomMember, User, WatchHistory
from backend.playback import PlaybackResolver
from backend.providers import CatalogService
from backend.schemas import DiscordAuthRequest, FavoriteCreate, ProgressCreate, RoomCreate, RoomView


router = APIRouter(prefix="/api")
catalog = CatalogService()
playback = PlaybackResolver()


@router.get("/health")
def health():
    settings = get_settings()
    return {
        "status": "ok", "service": "craftplay",
        "configuration": {
            "discord_client": bool(settings.discord_client_id),
            "discord_oauth": bool(settings.discord_client_id and settings.discord_client_secret),
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
async def sources(media_id: str, season: int = 0, episode: int = 0, user: User = Depends(current_user)):
    item = await catalog.details(media_id)
    if not item:
        raise HTTPException(status_code=404, detail="Conteúdo não encontrado")
    provider_type = "tv" if item.media_type in {"series", "anime", "cartoon"} else "movie"
    return {"sources": await playback.resolve(media_id, season, episode, imdb_id=item.external_ids.imdb, media_type=provider_type)}


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
        db.commit()
        db.refresh(favorite)
    return favorite


@router.delete("/user/favorites/{media_id:path}", status_code=204)
def remove_favorite(media_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    favorite = db.scalar(select(Favorite).where(Favorite.user_id == user.id, Favorite.media_id == media_id))
    if favorite:
        db.delete(favorite)
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
    return room


@router.get("/rooms/{room_id}", response_model=RoomView)
def get_room(room_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    room = db.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")
    return room
