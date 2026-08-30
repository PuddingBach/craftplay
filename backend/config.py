from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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
    tmdb_api_key: str = ""
    tmdb_read_access_token: str = ""
    plenoflu_enabled: bool = False
    database_url: str = "sqlite:///./craftplay.db"
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

    @field_validator("database_url")
    @classmethod
    def normalize_postgres(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://") and "+" not in value.split(":", 1)[0]:
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
