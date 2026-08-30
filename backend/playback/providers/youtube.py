from urllib.parse import parse_qs, urlparse

from backend.playback.base import PlaybackProvider
from backend.schemas import PlaybackSource


class YouTubeProvider(PlaybackProvider):
    name = "YouTube"

    def __init__(self, mappings: dict[str, str] | None = None):
        self.mappings = mappings or {}

    async def resolve(self, media_id: str, season: int = 0, episode: int = 0, **context) -> list[PlaybackSource]:
        url = self.mappings.get(media_id)
        if not url:
            return []
        parsed = urlparse(url)
        video_id = parse_qs(parsed.query).get("v", [parsed.path.rsplit("/", 1)[-1]])[0]
        return [PlaybackSource(provider_name=self.name, media_id=media_id, source_type="EMBED", embed_url=f"https://www.youtube.com/embed/{video_id}")]
