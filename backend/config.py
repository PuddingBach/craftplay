from functools import lru_cache
import logging
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "CraftPlay"
    environment: Literal["development", "test", "production"] = "development"
    discord_client_id: str = ""
    discord_client_secret: str = ""
    discord_bot_token: str = ""
    discord_public_key: str = ""
    discord_guild_id: str = ""
    discord_activity_url: str = "https://craftplay.shardweb.app"
    discord_redirect_uri: str = "https://craftplay.shardweb.app/auth/discord/callback"
    dashboard_channel_id: str = ""
    dashboard_allowed_role_ids: Annotated[list[str], NoDecode] = []
    dashboard_allowed_user_ids: Annotated[list[str], NoDecode] = []
    tmdb_api_key: str = ""
    tmdb_read_access_token: str = ""
    youtube_api_key: str = ""
    vimeo_access_token: str = ""
    admin_api_key: str = ""
    room_max_participants: int = 10
    max_browser_sessions: int = 5
    browser_width: int = 1920
    browser_height: int = 1080
    browser_fps: int = 30
    browser_idle_timeout: int = 1800
    browser_start_timeout: int = 30
    empty_room_grace_period: int = 120
    control_idle_timeout: int = 120
    browser_allow_downloads: bool = False
    browser_manual_url_enabled: bool = True
    browser_headless: bool = False
    browser_auto_install: bool = True
    browser_websocket_fallback: bool = True
    browser_frame_fps: int = 6
    browser_frame_quality: int = 55
    browser_homepage: str = "about:blank"
    browser_profile_root: str = "./browser_profiles"
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    playback_cache_ttl_seconds: int = 21600
    playback_validation_timeout: float = 10
    redecanais_provider_enabled: bool = False
    jw_player_enabled: bool = False
    jw_player_library_url: str = ""
    jw_player_license_key: str = ""
    plenoflu_enabled: bool = False
    database_url: str = "sqlite:///./craftplay.db"
    database_fallback_url: str = "sqlite:///./craftplay-fallback.db"
    redis_url: str = ""
    secret_key: str = "development-only-change-me"
    allowed_origins: Annotated[list[str], NoDecode] = [
        "https://craftplay.shardweb.app",
        "http://localhost:8000",
        "http://localhost:5173",
    ]
    port: int = 8000

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("dashboard_allowed_role_ids", "dashboard_allowed_user_ids", mode="before")
    @classmethod
    def split_discord_ids(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("browser_headless", mode="before")
    @classmethod
    def resilient_browser_headless(cls, value):
        if not isinstance(value, str):
            return value
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
        logger.warning("BROWSER_HEADLESS possui valor invalido; usando false")
        return False

    @field_validator("database_url")
    @classmethod
    def normalize_postgres(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://") and "+" not in value.split(":", 1)[0]:
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @field_validator("livekit_url")
    @classmethod
    def normalize_livekit_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if normalized.startswith("https://"):
            return "wss://" + normalized.removeprefix("https://")
        if normalized.startswith("http://"):
            return "ws://" + normalized.removeprefix("http://")
        return normalized


@lru_cache
def get_settings() -> Settings:
    return Settings()
