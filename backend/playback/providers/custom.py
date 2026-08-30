import logging

from sqlalchemy import select

from backend.database import SessionLocal
from backend.models import CustomSource
from backend.playback.base import PlaybackProvider
from backend.playback.validation import validate_media_url
from backend.schemas import MediaItem, PlaybackSource


OPEN_MOVIES = {
    "demo:big-buck-bunny": {"url": "https://archive.org/download/youtube-aqz-KE-bpKQ/aqz-KE-bpKQ.mp4",
                             "title": "Big Buck Bunny", "duration": 635, "license": "CC BY 3.0"},
    "demo:sintel": {"url": "https://archive.org/download/Sintel/sintel-2048-stereo_512kb.mp4",
                    "title": "Sintel", "duration": 888, "license": "CC BY 3.0"},
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
            demo = OPEN_MOVIES[media.id]
            candidates.append({"provider": "Blender Open Movie / Internet Archive", "url": demo["url"],
                               "type": "mp4", "quality": "720p", "language": "original",
                               "title": demo["title"], "duration": demo["duration"], "license": demo["license"]})
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
                              title=candidate.get("title") or media.title, license=candidate.get("license"),
                              metadata={"custom_source_id": candidate.get("id"), "duration": candidate.get("duration")})
