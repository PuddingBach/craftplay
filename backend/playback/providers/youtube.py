import logging
from difflib import SequenceMatcher

import httpx

from backend.playback.base import PlaybackProvider
from backend.config import get_settings
from backend.playback.matcher import MediaMatcher
from backend.playback.validation import normalized_title
from backend.schemas import MediaItem, PlaybackSource


class YouTubeProvider(PlaybackProvider):
    name = "youtube"
    priority = 40
    api_root = "https://www.googleapis.com/youtube/v3"

    def __init__(self):
        self.api_key = get_settings().youtube_api_key
        self.enabled = bool(self.api_key)

    async def search_sources(self, media: MediaItem, season: int = 0, episode: int = 0) -> list[dict]:
        if not self.enabled:
            return []
        suffix = f" S{season:02d}E{episode:02d}" if season and episode else " full movie official"
        params = {"part": "snippet", "q": f"{media.title}{suffix}", "type": "video", "maxResults": 5,
                  "videoEmbeddable": "true", "videoSyndicated": "true", "videoLicense": "creativeCommon",
                  "relevanceLanguage": "pt", "key": self.api_key}
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.get(f"{self.api_root}/search", params=params)
                response.raise_for_status()
            return [{"video_id": item["id"]["videoId"], "title": item["snippet"]["title"]}
                    for item in response.json().get("items", []) if item.get("id", {}).get("videoId")]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            logging.getLogger("craftplay.playback.youtube").warning("[YOUTUBE] Search failed: %s", exc)
            return []

    async def resolve(self, media: MediaItem, candidate: dict | None = None, season: int = 0, episode: int = 0) -> PlaybackSource | None:
        if not self.enabled or not candidate or not candidate.get("video_id"):
            return None
        expected = normalized_title(f"{media.title} S{season:02d}E{episode:02d}" if season and episode else media.title)
        if SequenceMatcher(None, expected, normalized_title(candidate.get("title", ""))).ratio() < 0.72:
            return None
        video_id = candidate["video_id"]
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.api_root}/videos", params={"part": "status,contentDetails", "id": video_id, "key": self.api_key})
                response.raise_for_status()
                items = response.json().get("items", [])
                if not items:
                    return None
                status = items[0].get("status", {})
                allowed = status.get("embeddable") is True and status.get("privacyStatus") == "public" and status.get("license") == "creativeCommon"
                if not allowed:
                    return None
                duration = self._duration_seconds(items[0].get("contentDetails", {}).get("duration", ""))
                if not MediaMatcher.is_full_content(media, candidate.get("title", ""), duration, season, episode):
                    return None
                embed_url = f"https://www.youtube.com/embed/{video_id}?enablejsapi=1"
                oembed = await client.get("https://www.youtube.com/oembed", params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"})
                if oembed.status_code != 200:
                    return None
            return PlaybackSource(provider=self.name, type="youtube", url=embed_url, media_id=media.id,
                                  quality="auto", language="original", is_playable=True,
                                  title=candidate.get("title"), license="Creative Commons",
                                  metadata={"video_id": video_id, "duration": duration})
        except (httpx.HTTPError, ValueError):
            return None

    @staticmethod
    def _duration_seconds(value: str) -> int:
        import re

        match = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
        if not match:
            return 0
        days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
        return days * 86400 + hours * 3600 + minutes * 60 + seconds

    async def healthcheck(self) -> dict:
        if not self.enabled:
            return {"name": self.name, "enabled": False, "healthy": False, "reason": "YOUTUBE_API_KEY nao configurada"}
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(f"{self.api_root}/videos", params={"part": "id", "id": "M7lc1UVf-VE", "key": self.api_key})
            return {"name": self.name, "enabled": True, "healthy": response.status_code == 200, "status": response.status_code}
        except httpx.HTTPError as exc:
            return {"name": self.name, "enabled": True, "healthy": False, "error": str(exc)}
