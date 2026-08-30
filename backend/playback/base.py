from abc import ABC, abstractmethod

from backend.schemas import PlaybackSource


class PlaybackProvider(ABC):
    name: str

    @abstractmethod
    async def resolve(self, media_id: str, season: int = 0, episode: int = 0, **context) -> list[PlaybackSource]:
        raise NotImplementedError
