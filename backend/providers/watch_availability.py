from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from backend.config import get_settings
from backend.database import SessionLocal
from backend.models import WatchAvailabilityCache
from backend.schemas import MediaItem


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class WatchAvailabilityProvider:
    """Informational storefront availability. Its output must never enter playback."""

    async def get(self, media: MediaItem) -> dict:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            cached = db.get(WatchAvailabilityCache, media.id)
            if cached and _aware(cached.expires_at) > now:
                return {"provider": cached.provider, "region": "BR", "items": cached.sources, "cached": True}
        settings = get_settings()
        items: list[dict] = []
        link = None
        if media.external_ids.tmdb and (settings.tmdb_api_key or settings.tmdb_read_access_token):
            kind = "tv" if media.media_type in {"series", "anime", "cartoon"} else "movie"
            params = {"api_key": settings.tmdb_api_key} if settings.tmdb_api_key else {}
            headers = {"Authorization": f"Bearer {settings.tmdb_read_access_token}"} if settings.tmdb_read_access_token else {}
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.get(f"https://api.themoviedb.org/3/{kind}/{media.external_ids.tmdb}/watch/providers", params=params, headers=headers)
                response.raise_for_status()
            br = response.json().get("results", {}).get("BR", {})
            link = br.get("link")
            seen = set()
            for offer_type in ("flatrate", "free", "ads", "rent", "buy"):
                for service in br.get(offer_type, []):
                    key = (service.get("provider_id"), offer_type)
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append({"name": service.get("provider_name"), "logo": f"https://image.tmdb.org/t/p/w92{service.get('logo_path')}" if service.get("logo_path") else None,
                                  "offer_type": offer_type, "provider_id": service.get("provider_id")})
        expires = now + timedelta(seconds=settings.playback_cache_ttl_seconds)
        with SessionLocal() as db:
            cached = db.get(WatchAvailabilityCache, media.id)
            if cached:
                cached.sources, cached.checked_at, cached.expires_at = items, now, expires
            else:
                db.add(WatchAvailabilityCache(media_id=media.id, provider="tmdb", sources=items, checked_at=now, expires_at=expires))
            db.commit()
        return {"provider": "tmdb", "region": "BR", "items": items, "link": link, "cached": False,
                "notice": "Disponibilidade informativa; estas lojas nao sao fontes do player."}
