import logging

from sqlalchemy import select

from backend.database import SessionLocal
from backend.models import CustomSource
from backend.playback.base import PlaybackProvider
from backend.playback.validation import validate_media_url
from backend.schemas import MediaItem, PlaybackSource


OPEN_MOVIES = {
    "demo:big-buck-bunny": "https://media.w3.org/2010/05/bunny/trailer.mp4",
    "demo:sintel": "https://media.w3.org/2010/05/sintel/trailer.mp4",
}


class CustomProvider(PlaybackProvider):
    name = "custom"
    priority = 100

    async def search_sources(self, media: MediaItem, season: int = 0, episode: int = 0) -> list[dict]:
        with SessionLocal() as db:
            rows = db.scalars(select(CustomSource).where(
                CustomSource.media_id == media.id, CustomSource.season == season,
                CustomSource.episode == episode, CustomSource.enabled.is_(True),
            )).all()
        candidates = [{"provider": row.provider, "url": row.url, "type": row.source_type,
                       "language": row.language, "quality": row.quality, "id": row.id} for row in rows]
        if media.id in OPEN_MOVIES and season == 0 and episode == 0:
            candidates.append({"provider": "W3C Open Media", "url": OPEN_MOVIES[media.id],
                               "type": "mp4", "quality": "original", "language": "original"})
        return candidates

    async def resolve(self, media: MediaItem, candidate: dict | None = None, season: int = 0, episode: int = 0) -> PlaybackSource | None:
        if not candidate:
            return None
        valid, reason = await validate_media_url(candidate["url"], candidate["type"])
        logging.getLogger("craftplay.playback.custom").info("[CUSTOM] %s: %s", candidate["url"], reason)
        if not valid:
            return None
        return PlaybackSource(provider=candidate.get("provider", self.name), type=candidate["type"], url=candidate["url"],
                              media_id=media.id, quality=candidate.get("quality", "auto"),
                              language=candidate.get("language", "original"), is_playable=True,
                              title=media.title, metadata={"custom_source_id": candidate.get("id")})
