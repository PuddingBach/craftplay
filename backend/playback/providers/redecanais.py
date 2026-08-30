import logging
from datetime import datetime, timezone

from backend.config import get_settings
from backend.playback.base import PlaybackProvider
from backend.playback.matcher import MediaMatcher
from backend.schemas import MediaItem, PlaybackSource


class RedeCanaisProvider(PlaybackProvider):
    """Safety boundary for a future officially authorized RedeCanais integration.

    No public, documented playback API or licensing signal is available. The
    provider therefore never scrapes pages or extracts streams/tokens.
    """

    name = "redecanais"
    priority = 80

    def __init__(self):
        self.enabled = get_settings().redecanais_provider_enabled
        self.matcher = MediaMatcher()
        self.last_reason = "FEATURE_DISABLED" if not self.enabled else "NO_AUTHORIZED_PUBLIC_API"

    async def search_sources(self, media: MediaItem, season: int = 0, episode: int = 0) -> list[dict]:
        self.last_reason = "NO_AUTHORIZED_PUBLIC_API"
        logging.getLogger("craftplay.playback.redecanais").warning("[REDECANAIS] %s; trying next provider", self.last_reason)
        return []

    async def resolve(self, media: MediaItem, candidate: dict | None = None, season: int = 0, episode: int = 0) -> PlaybackSource | None:
        self.last_reason = "SOURCE_RESTRICTED"
        return None

    async def healthcheck(self) -> dict:
        return {"name": self.name, "enabled": self.enabled, "healthy": False,
                "priority": self.priority, "last_check": datetime.now(timezone.utc).isoformat(),
                "reason": self.last_reason}
