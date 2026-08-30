import re
import time

import httpx

from backend.playback.base import PlaybackProvider
from backend.schemas import MediaItem, PlaybackSource


IMDB_PATTERN = re.compile(r"^tt\d{5,12}$")


def validate_imdb_id(imdb_id: str | None) -> bool:
    return bool(imdb_id and IMDB_PATTERN.fullmatch(imdb_id))


def build_plenoflu_movie_url(imdb_id: str | None) -> str | None:
    return f"https://plenoflu.com/movie/{imdb_id}" if validate_imdb_id(imdb_id) else None


def build_plenoflu_episode_url(imdb_id: str | None, season: int, episode: int) -> str | None:
    if not validate_imdb_id(imdb_id) or not isinstance(season, int) or not isinstance(episode, int) or season < 1 or episode < 1:
        return None
    return f"https://plenoflu.com/tvshow/{imdb_id}/{season}/{episode}"


class PlenoFluProvider(PlaybackProvider):
    """Official embed integration only; never extracts internal streams."""

    name = "plenoflu"

    def __init__(self):
        self._embed_allowed_until = 0.0
        self._embed_allowed_value = False

    async def _embed_allowed(self, url: str) -> bool:
        if time.monotonic() < self._embed_allowed_until:
            return self._embed_allowed_value
        allowed = False
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=8) as client:
                response = await client.head(url)
            x_frame_options = response.headers.get("x-frame-options", "").lower()
            content_security_policy = response.headers.get("content-security-policy", "").lower()
            blocked_by_xframe = "deny" in x_frame_options or "sameorigin" in x_frame_options
            blocked_by_csp = "frame-ancestors 'none'" in content_security_policy or "frame-ancestors 'self'" in content_security_policy
            allowed = response.is_success and not blocked_by_xframe and not blocked_by_csp
        except httpx.HTTPError:
            allowed = False
        self._embed_allowed_value = allowed
        self._embed_allowed_until = time.monotonic() + 600
        return allowed

    async def search_sources(self, media: MediaItem, season: int = 0, episode: int = 0) -> list[dict]:
        imdb_id = media.external_ids.imdb
        media_type = "tv" if media.media_type in {"series", "anime", "cartoon"} else "movie"
        url = build_plenoflu_movie_url(imdb_id) if media_type == "movie" else build_plenoflu_episode_url(imdb_id, season, episode)
        return [{"url": url, "type": "embed"}] if url else []

    async def resolve(self, media: MediaItem, candidate: dict | None = None, season: int = 0, episode: int = 0) -> PlaybackSource | None:
        url = candidate.get("url") if candidate else None
        if not url or not await self._embed_allowed(url):
            return None
        return PlaybackSource(provider=self.name, media_id=media.id, type="embed", url=url,
                              quality="externo", is_playable=True)

    async def healthcheck(self) -> dict:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=8) as client:
                response = await client.head("https://plenoflu.com")
            xframe = response.headers.get("x-frame-options", "").casefold()
            csp = response.headers.get("content-security-policy", "").casefold()
            embeddable = "deny" not in xframe and "sameorigin" not in xframe and "frame-ancestors 'self'" not in csp
            return {"name": self.name, "enabled": True, "healthy": response.is_success and embeddable,
                    "status": response.status_code, "reason": None if embeddable else "Incorporacao bloqueada pelo servidor"}
        except httpx.HTTPError as exc:
            return {"name": self.name, "enabled": True, "healthy": False, "error": str(exc)}
