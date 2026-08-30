import re

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

    async def resolve(self, media_id: str, season: int = 0, episode: int = 0, **context) -> list[PlaybackSource]:
        imdb_id = context.get("imdb_id")
        media_type = context.get("media_type")
        url = build_plenoflu_movie_url(imdb_id) if media_type == "movie" else build_plenoflu_episode_url(imdb_id, season, episode)
        if not url:
            return []
        return [PlaybackSource(provider_name=self.name, media_id=media_id, source_type="EMBED", embed_url=url, quality="externo")]

