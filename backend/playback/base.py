from abc import ABC
from typing import Any

from backend.schemas import MediaItem, PlaybackSource


class PlaybackProvider(ABC):
    """Contract for services that can return an actually playable video."""

    name = "provider"
    enabled = True

    def can_handle(self, media: MediaItem) -> bool:
        return self.enabled

    async def search_sources(self, media: MediaItem, season: int = 0, episode: int = 0) -> list[dict[str, Any]]:
        return []

    async def resolve(
        self, media: MediaItem, candidate: dict[str, Any] | None = None,
        season: int = 0, episode: int = 0,
    ) -> PlaybackSource | None:
        return None

    async def healthcheck(self) -> dict[str, Any]:
        return {"name": self.name, "enabled": self.enabled, "healthy": self.enabled}
