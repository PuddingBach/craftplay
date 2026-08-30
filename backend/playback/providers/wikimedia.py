from backend.playback.base import PlaybackProvider
from backend.schemas import PlaybackSource


class WikimediaProvider(PlaybackProvider):
    name = "Wikimedia Commons"

    def __init__(self, mappings: dict[str, str] | None = None):
        self.mappings = mappings or {}

    async def resolve(self, media_id: str, season: int = 0, episode: int = 0, **context) -> list[PlaybackSource]:
        url = self.mappings.get(media_id)
        if not url:
            return []
        source_type = "HLS" if ".m3u8" in url else "MP4"
        return [PlaybackSource(provider_name=self.name, media_id=media_id, source_type=source_type, stream_url=url)]
