from backend.playback.base import PlaybackProvider
from backend.schemas import PlaybackSource


class VimeoProvider(PlaybackProvider):
    name = "Vimeo"

    def __init__(self, mappings: dict[str, str] | None = None):
        self.mappings = mappings or {}

    async def resolve(self, media_id: str, season: int = 0, episode: int = 0, **context) -> list[PlaybackSource]:
        video_id = self.mappings.get(media_id)
        if not video_id:
            return []
        return [PlaybackSource(provider_name=self.name, media_id=media_id, source_type="EMBED", embed_url=f"https://player.vimeo.com/video/{video_id}")]
