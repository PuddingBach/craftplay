import time

from backend.config import get_settings
from backend.providers.demo import DemoProvider
from backend.providers.tmdb import TMDBProvider
from backend.schemas import MediaItem


class CatalogService:
    def __init__(self):
        settings = get_settings()
        self.demo = DemoProvider()
        self.tmdb = TMDBProvider(settings.tmdb_api_key, settings.tmdb_read_access_token) if settings.tmdb_api_key or settings.tmdb_read_access_token else None
        self.tmdb_error: str | None = None
        self._home_cache: dict[str, list[MediaItem]] | None = None
        self._home_cache_until = 0.0

    def status(self) -> dict:
        return {
            "tmdb_configured": self.tmdb is not None,
            "tmdb_available": self.tmdb is not None and self.tmdb_error is None,
            "tmdb_error": self.tmdb_error,
            "fallback_catalog": True,
        }

    async def home(self) -> dict[str, list[MediaItem]]:
        if self._home_cache and time.monotonic() < self._home_cache_until:
            return self._home_cache
        demo = await self.demo.home()
        if not self.tmdb:
            return demo
        try:
            remote = await self.tmdb.home()
            self.tmdb_error = None
            self._home_cache = {key: (demo.get(key, []) + remote.get(key, []))[:24] for key in set(demo) | set(remote)}
            self._home_cache_until = time.monotonic() + 300
            return self._home_cache
        except Exception as exc:
            self.tmdb_error = f"{type(exc).__name__}: {exc}"
            return demo

    async def search(self, query: str, page: int = 1) -> list[MediaItem]:
        local = await self.demo.search(query, page)
        if not self.tmdb or not query.strip():
            return local
        try:
            remote = await self.tmdb.search(query, page)
            self.tmdb_error = None
            return local + remote
        except Exception as exc:
            self.tmdb_error = f"{type(exc).__name__}: {exc}"
            return local

    async def details(self, media_id: str) -> MediaItem | None:
        if media_id.startswith("demo:"):
            return await self.demo.details(media_id)
        if media_id.startswith("tmdb:") and self.tmdb:
            try:
                return await self.tmdb.details(media_id)
            except Exception:
                return None
        return None

    async def recommendations(self, media_id: str) -> list[MediaItem]:
        if media_id.startswith("demo:"):
            return await self.demo.recommendations(media_id)
        if media_id.startswith("tmdb:") and self.tmdb:
            try:
                return await self.tmdb.recommendations(media_id)
            except Exception:
                return []
        return []
