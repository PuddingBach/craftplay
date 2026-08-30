from backend.playback.base import PlaybackProvider
from backend.schemas import PlaybackSource


OPEN_MOVIES = {
    "demo:big-buck-bunny": "https://media.w3.org/2010/05/bunny/trailer.mp4",
    "demo:sintel": "https://media.w3.org/2010/05/sintel/trailer.mp4",
}


class CustomProvider(PlaybackProvider):
    name = "Open Movies (W3C)"

    async def resolve(self, media_id: str, season: int = 0, episode: int = 0, **context) -> list[PlaybackSource]:
        url = OPEN_MOVIES.get(media_id)
        if not url:
            return []
        return [PlaybackSource(provider_name=self.name, media_id=media_id, source_type="MP4", stream_url=url, quality="original")]
