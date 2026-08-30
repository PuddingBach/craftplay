import pytest

from backend.playback.providers.plenoflu import (
    PlenoFluProvider,
    build_plenoflu_episode_url,
    build_plenoflu_movie_url,
    validate_imdb_id,
)
from backend.playback.resolver import PlaybackResolver


def test_plenoflu_builders_reject_arbitrary_values():
    assert validate_imdb_id("tt1234567")
    assert not validate_imdb_id("https://example.com/video")
    assert not validate_imdb_id("tt12/path")
    assert build_plenoflu_movie_url("tt1234567") == "https://plenoflu.com/movie/tt1234567"
    assert build_plenoflu_movie_url("invalid") is None
    assert build_plenoflu_episode_url("tt1234567", 2, 4) == "https://plenoflu.com/tvshow/tt1234567/2/4"
    assert build_plenoflu_episode_url("tt1234567", 0, 4) is None


@pytest.mark.asyncio
async def test_plenoflu_provider_is_embed_only():
    sources = await PlenoFluProvider().resolve("tmdb:movie:1", imdb_id="tt1234567", media_type="movie")
    assert len(sources) == 1
    assert sources[0].source_type == "EMBED"
    assert sources[0].stream_url is None


@pytest.mark.asyncio
async def test_demo_resolver_returns_legal_sample():
    resolver = PlaybackResolver()
    sources = await resolver.resolve("demo:big-buck-bunny", media_type="movie")
    assert sources
    assert sources[0].source_type == "MP4"
    assert "media.w3.org" in sources[0].stream_url
