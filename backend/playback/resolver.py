from backend.playback.base import PlaybackProvider
from backend.config import get_settings
from backend.playback.providers import ArchiveProvider, CustomProvider, PlenoFluProvider, VimeoProvider, WikimediaProvider, YouTubeProvider
from backend.schemas import PlaybackSource


class PlaybackResolver:
    """Resolves only explicitly registered, authorized media sources."""

    def __init__(self, providers: list[PlaybackProvider] | None = None):
        if providers is not None:
            self.providers = providers
        else:
            self.providers = [CustomProvider(), YouTubeProvider(), VimeoProvider(), ArchiveProvider(), WikimediaProvider()]
            if get_settings().plenoflu_enabled:
                self.providers.append(PlenoFluProvider())

    async def resolve(self, media_id: str, season: int = 0, episode: int = 0, **context) -> list[PlaybackSource]:
        lookup_id = f"{media_id}:s{season}:e{episode}" if season and episode else media_id
        sources: list[PlaybackSource] = []
        for provider in self.providers:
            sources.extend(await provider.resolve(lookup_id, season, episode, **context))
        if not sources and lookup_id != media_id:
            for provider in self.providers:
                sources.extend(await provider.resolve(media_id, season, episode, **context))
        return sources
