from abc import ABC, abstractmethod

from backend.schemas import MediaItem


class MetadataProvider(ABC):
    name: str

    @abstractmethod
    async def home(self) -> dict[str, list[MediaItem]]:
        raise NotImplementedError

    @abstractmethod
    async def search(self, query: str, page: int = 1) -> list[MediaItem]:
        raise NotImplementedError

    @abstractmethod
    async def details(self, media_id: str) -> MediaItem | None:
        raise NotImplementedError

    async def recommendations(self, media_id: str) -> list[MediaItem]:
        return []

