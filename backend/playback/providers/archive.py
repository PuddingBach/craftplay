import logging
from difflib import SequenceMatcher
from urllib.parse import quote

import httpx

from backend.playback.base import PlaybackProvider
from backend.playback.validation import normalized_title, validate_media_url
from backend.schemas import MediaItem, PlaybackSource


class ArchiveProvider(PlaybackProvider):
    name = "archive"
    search_url = "https://archive.org/advancedsearch.php"

    async def search_sources(self, media: MediaItem, season: int = 0, episode: int = 0) -> list[dict]:
        episode_label = f" S{season:02d}E{episode:02d}" if season and episode else ""
        title = f"{media.title}{episode_label}"
        query = f'title:("{title}") AND mediatype:movies'
        params = {"q": query, "fl[]": ["identifier", "title", "year", "licenseurl", "rights"],
                  "rows": 5, "page": 1, "output": "json"}
        try:
            async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
                response = await client.get(self.search_url, params=params)
                response.raise_for_status()
            docs = response.json().get("response", {}).get("docs", [])
            logging.getLogger("craftplay.playback.archive").info("[ARCHIVE] %d results found for %s", len(docs), title)
            return docs
        except (httpx.HTTPError, ValueError) as exc:
            logging.getLogger("craftplay.playback.archive").warning("[ARCHIVE] Search failed: %s", exc)
            return []

    async def resolve(self, media: MediaItem, candidate: dict | None = None, season: int = 0, episode: int = 0) -> PlaybackSource | None:
        if not candidate or not candidate.get("identifier"):
            return None
        expected = normalized_title(f"{media.title} S{season:02d}E{episode:02d}" if season and episode else media.title)
        found = normalized_title(str(candidate.get("title", "")))
        if SequenceMatcher(None, expected, found).ratio() < 0.68:
            return None
        if media.year and candidate.get("year"):
            try:
                if abs(int(str(candidate["year"])[:4]) - media.year) > 1:
                    return None
            except ValueError:
                return None
        identifier = candidate["identifier"]
        try:
            async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
                response = await client.get(f"https://archive.org/metadata/{quote(identifier, safe='')}")
                response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        metadata = data.get("metadata", {})
        license_value = metadata.get("licenseurl") or metadata.get("license") or metadata.get("rights")
        if not license_value:
            return None
        files = sorted(data.get("files", []), key=lambda item: ("mpeg4" not in str(item.get("format", "")).casefold(), item.get("size", "0")), reverse=False)
        for item in files:
            name = str(item.get("name", ""))
            fmt = str(item.get("format", "")).casefold()
            if not (name.casefold().endswith((".mp4", ".webm", ".ogv")) or any(x in fmt for x in ("mpeg4", "h.264", "webm", "ogg video"))):
                continue
            url = f"https://archive.org/download/{quote(identifier, safe='')}/{quote(name)}"
            valid, reason = await validate_media_url(url, "mp4")
            logging.getLogger("craftplay.playback.archive").info("[ARCHIVE] Checking %s: %s", name, reason)
            if valid:
                return PlaybackSource(provider=self.name, type="mp4", url=url, media_id=media.id,
                                      quality="auto", language="original", is_playable=True,
                                      title=str(candidate.get("title") or media.title), license=str(license_value),
                                      metadata={"identifier": identifier, "filename": name})
        return None

    async def healthcheck(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(self.search_url, params={"q": "mediatype:movies", "rows": 0, "output": "json"})
            healthy = response.status_code == 200
            return {"name": self.name, "enabled": True, "healthy": healthy, "status": response.status_code}
        except httpx.HTTPError as exc:
            return {"name": self.name, "enabled": True, "healthy": False, "error": str(exc)}
