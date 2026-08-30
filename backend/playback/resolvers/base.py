from abc import ABC, abstractmethod

from backend.schemas import MediaItem, PlaybackSource


class SourceResolver(ABC):
    @abstractmethod
    async def resolve(self, media: MediaItem, candidate: dict) -> PlaybackSource | None:
        raise NotImplementedError
