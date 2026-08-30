import logging
from difflib import SequenceMatcher

import httpx

from backend.playback.base import PlaybackProvider
from backend.playback.validation import normalized_title, validate_media_url
from backend.schemas import MediaItem, PlaybackSource


class WikimediaProvider(PlaybackProvider):
    name = "wikimedia"
    priority = 20
    api_url = "https://commons.wikimedia.org/w/api.php"

    async def search_sources(self, media: MediaItem, season: int = 0, episode: int = 0) -> list[dict]:
        suffix = f" S{season:02d}E{episode:02d}" if season and episode else ""
        params = {"action": "query", "format": "json", "generator": "search", "gsrsearch": f"{media.title}{suffix} filetype:video",
                  "gsrnamespace": 6, "gsrlimit": 8, "prop": "imageinfo", "iiprop": "url|mime|extmetadata", "origin": "*"}
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.get(self.api_url, params=params)
                response.raise_for_status()
            return list(response.json().get("query", {}).get("pages", {}).values())
        except (httpx.HTTPError, ValueError) as exc:
            logging.getLogger("craftplay.playback.wikimedia").warning("[WIKIMEDIA] Search failed: %s", exc)
            return []

    async def resolve(self, media: MediaItem, candidate: dict | None = None, season: int = 0, episode: int = 0) -> PlaybackSource | None:
        if not candidate or not candidate.get("imageinfo"):
            return None
        info = candidate["imageinfo"][0]
        mime = str(info.get("mime", "")).casefold()
        url = info.get("url")
        license_name = (info.get("extmetadata", {}).get("LicenseShortName") or {}).get("value")
        if not url or not mime.startswith("video/") or not license_name:
            return None
        expected = normalized_title(f"{media.title} S{season:02d}E{episode:02d}" if season and episode else media.title)
        found = normalized_title(str(candidate.get("title", "")))
        if SequenceMatcher(None, expected, found).ratio() < 0.45:
            return None
        valid, reason = await validate_media_url(url, "mp4")
        logging.getLogger("craftplay.playback.wikimedia").info("[WIKIMEDIA] %s: %s", candidate.get("title"), reason)
        if not valid:
            return None
        return PlaybackSource(provider=self.name, type="mp4", url=url, media_id=media.id, quality="auto",
                              language="original", is_playable=True, title=candidate.get("title"),
                              license=license_name, metadata={"mime": mime})

    async def healthcheck(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(self.api_url, params={"action": "query", "format": "json", "meta": "siteinfo"})
            return {"name": self.name, "enabled": True, "healthy": response.status_code == 200, "status": response.status_code}
        except httpx.HTTPError as exc:
            return {"name": self.name, "enabled": True, "healthy": False, "error": str(exc)}
