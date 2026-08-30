from backend.playback.base import PlaybackProvider
from backend.schemas import PlaybackSource


class ArchiveProvider(PlaybackProvider):
    name = "Internet Archive"

    def __init__(self, mappings: dict[str, str] | None = None):
        self.mappings = mappings or {}

    async def resolve(self, media_id: str, season: int = 0, episode: int = 0, **context) -> list[PlaybackSource]:
        identifier = self.mappings.get(media_id)
        if not identifier:
            return []
        return [PlaybackSource(provider_name=self.name, media_id=media_id, source_type="EMBED", embed_url=f"https://archive.org/embed/{identifier}")]
