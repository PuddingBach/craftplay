from backend.playback.resolvers.base import SourceResolver
from backend.playback.validation import detect_source_type, validate_media_url
from backend.schemas import MediaItem, PlaybackSource


class MediaResolver(SourceResolver):
    """Validates a direct, already-authorized public media URL."""

    async def resolve(self, media: MediaItem, candidate: dict) -> PlaybackSource | None:
        url = candidate.get("url", "")
        source_type = candidate.get("type") or detect_source_type(url, candidate.get("content_type", ""))
        if source_type not in {"hls", "dash", "mp4", "webm"}:
            return None
        valid, reason = await validate_media_url(url, source_type)
        if not valid:
            return None
        return PlaybackSource(provider=candidate.get("provider", "media"), type=source_type, url=url,
                              media_id=media.id, quality=candidate.get("quality", "auto"),
                              language=candidate.get("language", "original"), is_playable=True,
                              license=candidate.get("license"), metadata={"validation": reason})
