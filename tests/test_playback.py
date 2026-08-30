import pytest

from backend.database import init_db
from backend.playback.providers.custom import CustomProvider
from backend.playback.providers.plenoflu import PlenoFluProvider, build_plenoflu_episode_url, build_plenoflu_movie_url, validate_imdb_id
from backend.playback.resolver import PlaybackResolver
from backend.playback.validation import is_public_https_url
from backend.schemas import ExternalIds, MediaItem


def media(media_id="tmdb:movie:1", media_type="movie"):
    return MediaItem(id=media_id, title="Example", media_type=media_type,
                     external_ids=ExternalIds(imdb="tt1234567"))


def test_plenoflu_builders_reject_arbitrary_values():
    assert validate_imdb_id("tt1234567")
    assert not validate_imdb_id("https://example.com/video")
    assert not validate_imdb_id("tt12/path")
    assert build_plenoflu_movie_url("tt1234567") == "https://plenoflu.com/movie/tt1234567"
    assert build_plenoflu_movie_url("invalid") is None
    assert build_plenoflu_episode_url("tt1234567", 2, 4) == "https://plenoflu.com/tvshow/tt1234567/2/4"


def test_source_validation_rejects_local_and_insecure_urls():
    assert is_public_https_url("https://media.w3.org/video.mp4")
    assert not is_public_https_url("http://media.w3.org/video.mp4")
    assert not is_public_https_url("https://127.0.0.1/video.mp4")
    assert not is_public_https_url("https://localhost/video.mp4")


@pytest.mark.asyncio
async def test_plenoflu_provider_returns_only_verified_embed(monkeypatch):
    provider = PlenoFluProvider()
    monkeypatch.setattr(provider, "_embed_allowed", lambda url: _async(True))
    item = media()
    candidate = (await provider.search_sources(item))[0]
    source = await provider.resolve(item, candidate)
    assert source.type == "embed"
    assert source.is_playable
    assert source.url == "https://plenoflu.com/movie/tt1234567"


async def _async(value):
    return value


@pytest.mark.asyncio
async def test_demo_resolver_returns_validated_legal_sample(monkeypatch):
    init_db()
    async def valid(url, source_type):
        return True, "HTTP 206 video/mp4"
    monkeypatch.setattr("backend.playback.providers.custom.validate_media_url", valid)
    item = media("demo:big-buck-bunny")
    resolver = PlaybackResolver(providers=[CustomProvider()])
    sources = await resolver.resolve(item, refresh=True)
    assert sources[0].type == "mp4"
    assert sources[0].is_playable is True
    assert "media.w3.org" in sources[0].url


@pytest.mark.asyncio
async def test_episode_keys_do_not_share_cache(monkeypatch):
    init_db()
    async def valid(url, source_type):
        return True, "ok"
    monkeypatch.setattr("backend.playback.providers.custom.validate_media_url", valid)
    resolver = PlaybackResolver(providers=[CustomProvider()])
    item = media("demo:sintel", "series")
    movie_sources = await resolver.resolve(item, 0, 0, refresh=True)
    episode_sources = await resolver.resolve(item, 1, 1, refresh=True)
    assert movie_sources
    assert episode_sources == []
