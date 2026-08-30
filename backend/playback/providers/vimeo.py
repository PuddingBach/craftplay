import logging
from difflib import SequenceMatcher

import httpx

from backend.config import get_settings
from backend.playback.base import PlaybackProvider
from backend.playback.validation import normalized_title
from backend.schemas import MediaItem, PlaybackSource


class VimeoProvider(PlaybackProvider):
    name = "vimeo"
    priority = 30

    def __init__(self):
        self.token = get_settings().vimeo_access_token
        self.enabled = bool(self.token)

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.vimeo.*+json;version=3.4"}

    async def search_sources(self, media: MediaItem, season: int = 0, episode: int = 0) -> list[dict]:
        if not self.enabled:
            return []
        suffix = f" S{season:02d}E{episode:02d}" if season and episode else ""
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.get("https://api.vimeo.com/videos", headers=self.headers,
                                            params={"query": f"{media.title}{suffix}", "per_page": 5, "fields": "uri,name,license,is_playable,privacy"})
                response.raise_for_status()
            return response.json().get("data", [])
        except (httpx.HTTPError, ValueError) as exc:
            logging.getLogger("craftplay.playback.vimeo").warning("[VIMEO] Search failed: %s", exc)
            return []

    async def resolve(self, media: MediaItem, candidate: dict | None = None, season: int = 0, episode: int = 0) -> PlaybackSource | None:
        if not candidate or not candidate.get("uri") or not candidate.get("is_playable") or not candidate.get("license"):
            return None
        expected = normalized_title(f"{media.title} S{season:02d}E{episode:02d}" if season and episode else media.title)
        if SequenceMatcher(None, expected, normalized_title(candidate.get("name", ""))).ratio() < 0.42:
            return None
        privacy = candidate.get("privacy") or {}
        if privacy.get("embed") not in {"public", "whitelist"}:
            return None
        video_id = str(candidate["uri"]).rsplit("/", 1)[-1]
        page_url = f"https://vimeo.com/{video_id}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                oembed = await client.get("https://vimeo.com/api/oembed.json", params={"url": page_url})
                if oembed.status_code != 200 or oembed.json().get("domain_status_code") == 403:
                    return None
        except (httpx.HTTPError, ValueError):
            return None
        return PlaybackSource(provider=self.name, type="vimeo", url=f"https://player.vimeo.com/video/{video_id}",
                              media_id=media.id, quality="auto", language="original", is_playable=True,
                              title=candidate.get("name"), license=candidate.get("license"), metadata={"video_id": video_id})

    async def healthcheck(self) -> dict:
        if not self.enabled:
            return {"name": self.name, "enabled": False, "healthy": False, "reason": "VIMEO_ACCESS_TOKEN nao configurado"}
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get("https://api.vimeo.com/me", headers=self.headers)
            return {"name": self.name, "enabled": True, "healthy": response.status_code == 200, "status": response.status_code}
        except httpx.HTTPError as exc:
            return {"name": self.name, "enabled": True, "healthy": False, "error": str(exc)}
