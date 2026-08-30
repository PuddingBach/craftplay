import re
import time

import httpx

from backend.playback.base import PlaybackProvider
from backend.schemas import PlaybackSource


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

    name = "PlenoFlu"

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

    async def resolve(self, media_id: str, season: int = 0, episode: int = 0, **context) -> list[PlaybackSource]:
        imdb_id = context.get("imdb_id")
        media_type = context.get("media_type")
        url = build_plenoflu_movie_url(imdb_id) if media_type == "movie" else build_plenoflu_episode_url(imdb_id, season, episode)
        if not url or not await self._embed_allowed(url):
            return []
        return [PlaybackSource(provider_name=self.name, media_id=media_id, source_type="EMBED", embed_url=url, quality="externo")]
