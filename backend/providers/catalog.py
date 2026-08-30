from backend.config import get_settings
from backend.providers.demo import DemoProvider
from backend.providers.tmdb import TMDBProvider
from backend.schemas import MediaItem


class CatalogService:
    def __init__(self):
        settings = get_settings()
        self.demo = DemoProvider()
        self.tmdb = TMDBProvider(settings.tmdb_api_key) if settings.tmdb_api_key else None

    async def home(self) -> dict[str, list[MediaItem]]:
        demo = await self.demo.home()
        if not self.tmdb:
            return demo
        try:
            remote = await self.tmdb.home()
            return {key: (demo.get(key, []) + remote.get(key, []))[:24] for key in set(demo) | set(remote)}
        except Exception:
            return demo

    async def search(self, query: str, page: int = 1) -> list[MediaItem]:
        local = await self.demo.search(query, page)
        if not self.tmdb or not query.strip():
            return local
        try:
            return local + await self.tmdb.search(query, page)
        except Exception:
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

