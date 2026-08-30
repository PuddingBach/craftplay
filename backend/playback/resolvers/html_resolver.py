from backend.playback.resolvers.base import SourceResolver
from backend.schemas import MediaItem, PlaybackSource


class HtmlResolver(SourceResolver):
    """Deliberately does not extract streams from arbitrary HTML pages."""

    async def resolve(self, media: MediaItem, candidate: dict) -> PlaybackSource | None:
        return None
