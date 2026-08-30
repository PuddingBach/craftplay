import pytest

from backend.database import init_db
from backend.playback.providers.custom import CustomProvider
from backend.playback.base import PlaybackProvider
from backend.playback.providers.plenoflu import PlenoFluProvider, build_plenoflu_episode_url, build_plenoflu_movie_url, validate_imdb_id
from backend.playback.providers.redecanais import RedeCanaisProvider
from backend.playback.matcher import MediaMatcher
from backend.playback.registry import ProviderRegistry
from backend.playback.resolver import PlaybackResolver
from backend.playback.validation import detect_source_type, is_public_https_url
from backend.schemas import ExternalIds, MediaItem
from backend.schemas import PlaybackSource


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
    assert detect_source_type("https://cdn.example/video.m3u8") == "hls"
    assert detect_source_type("https://cdn.example/manifest", "application/dash+xml") == "dash"
    assert detect_source_type("https://cdn.example/video.webm") == "webm"


def test_media_matcher_requires_exact_episode():
    item = MediaItem(id="anime:1", title="Attack on Titan", original_title="Shingeki no Kyojin",
                     media_type="anime", year=2013, tags=["Shingeki no Kyojin"])
    matcher = MediaMatcher()
    accepted = matcher.match(item, {"title": "Shingeki no Kyojin", "year": 2013, "media_type": "anime", "season": 1, "episode": 3}, 1, 3)
    rejected = matcher.match(item, {"title": "Attack on Titan", "year": 2013, "media_type": "anime", "season": 1, "episode": 4}, 1, 3)
    assert accepted.accepted and accepted.score >= 70
    assert not rejected.accepted and "episode_mismatch" in rejected.reasons


def test_media_matcher_rejects_trailers_reels_and_short_content():
    movie = MediaItem(id="movie:1", title="Example Movie", media_type="movie", duration=120)
    assert not MediaMatcher.is_full_content(movie, "Example Movie Official Trailer", 180)
    assert not MediaMatcher.is_full_content(movie, "Example Movie", 1200)
    assert MediaMatcher.is_full_content(movie, "Example Movie", 6500)
    series = MediaItem(id="tv:1", title="Example Show", media_type="series")
    assert not MediaMatcher.is_full_content(series, "Example Show atriz interview", 1500, 1, 3)
    assert not MediaMatcher.is_full_content(series, "Example Show", 1500, 0, 0)
    assert MediaMatcher.is_full_content(series, "Example Show S01E03", 1500, 1, 3)


def test_provider_registry_orders_and_toggles():
    custom, redecanais = CustomProvider(), RedeCanaisProvider()
    registry = ProviderRegistry([redecanais, custom])
    assert registry.get_providers()[0].name == "custom"
    registry.enable("redecanais")
    assert [provider.name for provider in registry.get_providers()] == ["custom", "redecanais"]
    registry.disable("redecanais")
    assert "redecanais" not in [provider.name for provider in registry.get_providers()]


@pytest.mark.asyncio
async def test_redecanais_never_extracts_without_authorized_api(monkeypatch):
    provider = RedeCanaisProvider()
    provider.enabled = True
    assert await provider.search_sources(media()) == []
    assert provider.last_reason == "NO_AUTHORIZED_PUBLIC_API"
    status = await provider.healthcheck()
    assert not status["healthy"]


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
    assert "archive.org" in sources[0].url
    assert sources[0].metadata["duration"] >= 600


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


@pytest.mark.asyncio
async def test_resolver_can_exclude_failed_provider_for_fallback():
    class FakeProvider(PlaybackProvider):
        def __init__(self, name, priority): self.name, self.priority = name, priority
        async def search_sources(self, media, season=0, episode=0): return [{"url": f"https://example.com/{self.name}.mp4"}]
        async def resolve(self, media, candidate=None, season=0, episode=0):
            return PlaybackSource(provider=self.name, type="mp4", url=candidate["url"], media_id=media.id, is_playable=True)
    resolver = PlaybackResolver(providers=[FakeProvider("primary", 100), FakeProvider("fallback", 50)])
    sources = await resolver.resolve(media(), exclude_providers={"primary"})
    assert [source.provider for source in sources] == ["fallback"]
