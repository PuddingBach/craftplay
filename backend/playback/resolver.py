import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from backend.config import get_settings
from backend.database import SessionLocal
from backend.models import PlaybackSourceCache
from backend.playback.base import PlaybackProvider
from backend.playback.providers import ArchiveProvider, CustomProvider, PlenoFluProvider, VimeoProvider, WikimediaProvider, YouTubeProvider
from backend.schemas import MediaItem, PlaybackSource
from backend.providers.anime_resolver import AnimeMetadataResolver


log = logging.getLogger("craftplay.playback")
QUALITY_ORDER = {"1080p": 0, "720p": 1, "480p": 2, "360p": 3, "original": 4, "auto": 5}


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class PlaybackResolver:
    """Searches legal providers and returns only sources validated by them."""

    def __init__(self, providers: list[PlaybackProvider] | None = None):
        self.anime_metadata = AnimeMetadataResolver()
        if providers is not None:
            self.providers = providers
        else:
            self.providers = [CustomProvider(), ArchiveProvider(), YouTubeProvider(), VimeoProvider(), WikimediaProvider()]
            if get_settings().plenoflu_enabled:
                self.providers.append(PlenoFluProvider())

    @staticmethod
    def _sort(source: PlaybackSource) -> tuple:
        language = source.language.casefold()
        return (0 if language.startswith("pt") else 1, QUALITY_ORDER.get(source.quality.casefold(), 6))

    async def resolve(self, media: MediaItem, season: int = 0, episode: int = 0, refresh: bool = False) -> list[PlaybackSource]:
        now = datetime.now(timezone.utc)
        if not refresh:
            with SessionLocal() as db:
                cached = db.scalar(select(PlaybackSourceCache).where(
                    PlaybackSourceCache.media_id == media.id, PlaybackSourceCache.season == season,
                    PlaybackSourceCache.episode == episode,
                ))
                if cached and _aware(cached.expires_at) > now:
                    return [PlaybackSource.model_validate(item) for item in cached.sources]
        log.info('[PLAYBACK] Searching source: "%s" s=%d e=%d', media.title, season, episode)
        if media.media_type == "anime":
            media = media.model_copy(deep=True)
            media.tags = list(dict.fromkeys([*media.tags, *(await self.anime_metadata.resolve(media))]))
        sources: list[PlaybackSource] = []
        for provider in self.providers:
            if not provider.can_handle(media):
                continue
            candidates = await provider.search_sources(media, season, episode)
            log.info("[%s] %d candidates found", provider.name.upper(), len(candidates))
            resolved = await asyncio.gather(
                *(provider.resolve(media, candidate, season, episode) for candidate in candidates),
                return_exceptions=True,
            )
            for source in resolved:
                if isinstance(source, PlaybackSource) and source.is_playable:
                    sources.append(source)
            if sources:
                break
        sources.sort(key=self._sort)
        if sources:
            top = sources[0]
            log.info("[PLAYBACK] Selected source: %s / %s / %s", top.provider, top.type, top.quality)
        payload = [item.model_dump(mode="json") for item in sources]
        with SessionLocal() as db:
            cached = db.scalar(select(PlaybackSourceCache).where(
                PlaybackSourceCache.media_id == media.id, PlaybackSourceCache.season == season,
                PlaybackSourceCache.episode == episode,
            ))
            expires = now + timedelta(seconds=get_settings().playback_cache_ttl_seconds)
            if cached:
                cached.sources, cached.checked_at, cached.expires_at = payload, now, expires
            else:
                db.add(PlaybackSourceCache(media_id=media.id, season=season, episode=episode,
                                           sources=payload, checked_at=now, expires_at=expires))
            db.commit()
        return sources

    async def debug(self, media: MediaItem, season: int = 0, episode: int = 0) -> list[dict]:
        results = []
        for provider in self.providers:
            entry = {"name": provider.name, "enabled": provider.enabled, "candidates": 0, "sources": [], "status": "disabled"}
            if provider.can_handle(media):
                try:
                    candidates = await provider.search_sources(media, season, episode)
                    entry["candidates"] = len(candidates)
                    for candidate in candidates:
                        source = await provider.resolve(media, candidate, season, episode)
                        if source:
                            entry["sources"].append(source.model_dump(mode="json"))
                    entry["status"] = "playable" if entry["sources"] else "not_found"
                except Exception as exc:
                    log.exception("Provider debug failed: %s", provider.name)
                    entry.update(status="error", error=f"{type(exc).__name__}: {exc}")
            results.append(entry)
        return results

    async def status(self) -> list[dict]:
        return list(await asyncio.gather(*(provider.healthcheck() for provider in self.providers)))

    @staticmethod
    def invalidate(media_id: str | None = None) -> None:
        with SessionLocal() as db:
            query = delete(PlaybackSourceCache)
            if media_id:
                query = query.where(PlaybackSourceCache.media_id == media_id)
            db.execute(query)
            db.commit()
