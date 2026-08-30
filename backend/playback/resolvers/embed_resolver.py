from backend.playback.resolvers.base import SourceResolver
from backend.playback.validation import validate_media_url
from backend.schemas import MediaItem, PlaybackSource


class EmbedResolver(SourceResolver):
    async def resolve(self, media: MediaItem, candidate: dict) -> PlaybackSource | None:
        url = candidate.get("url", "")
        valid, reason = await validate_media_url(url, "embed")
        if not valid:
            return None
        return PlaybackSource(provider=candidate.get("provider", "embed"), type="embed", url=url,
                              media_id=media.id, quality=candidate.get("quality", "auto"),
                              language=candidate.get("language", "original"), is_playable=True,
                              license=candidate.get("license"), metadata={"validation": reason})
