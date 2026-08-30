from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


MediaType = Literal["movie", "series", "anime", "cartoon"]


class ExternalIds(BaseModel):
    tmdb: int | None = None
    imdb: str | None = None
    provider: str | None = None


class Episode(BaseModel):
    id: str
    number: int
    title: str
    overview: str = ""
    duration: int | None = None
    thumbnail: str | None = None


class Season(BaseModel):
    number: int
    title: str
    episodes: list[Episode] = []


class MediaItem(BaseModel):
    id: str
    external_ids: ExternalIds = ExternalIds()
    title: str
    original_title: str = ""
    overview: str = ""
    media_type: MediaType
    genres: list[str] = []
    poster: str | None = None
    backdrop: str | None = None
    release_date: date | None = None
    year: int | None = None
    duration: int | None = None
    rating: float = 0
    popularity: float = 0
    cast: list[str] = []
    director: str | None = None
    certification: str | None = None
    trailer: str | None = None
    status: str | None = None
    seasons: list[Season] = []
    tags: list[str] = []


class SubtitleTrack(BaseModel):
    label: str
    language: str
    url: str


class AudioTrack(BaseModel):
    label: str
    language: str


class PlaybackSource(BaseModel):
    provider_name: str
    media_id: str
    source_type: Literal["HLS", "DASH", "MP4", "EMBED"]
    stream_url: str | None = None
    embed_url: str | None = None
    subtitles: list[SubtitleTrack] = []
    audio_tracks: list[AudioTrack] = []
    quality: str = "auto"


class FavoriteCreate(BaseModel):
    media_id: str
    media_type: MediaType


class ProgressCreate(BaseModel):
    media_id: str
    media_type: MediaType
    season: int = 0
    episode: int = 0
    position: float = Field(ge=0)
    duration: float = Field(ge=0)


class RoomCreate(BaseModel):
    discord_instance_id: str = Field(min_length=1, max_length=100)


class DiscordAuthRequest(BaseModel):
    code: str


class UserView(BaseModel):
    discord_id: str
    username: str
    avatar: str | None = None


class RoomView(BaseModel):
    id: str
    discord_instance_id: str
    host_user_id: int | None
    current_media: str | None
    current_season: int
    current_episode: int
    position: float
    state: str
    playback_rate: float
    subtitle: str | None
    audio_track: str | None
    updated_at: datetime

