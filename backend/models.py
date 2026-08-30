import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    discord_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(100))
    avatar: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WatchHistory(Base):
    __tablename__ = "watch_history"
    __table_args__ = (UniqueConstraint("user_id", "media_id", "season", "episode"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    media_id: Mapped[str] = mapped_column(String(100), index=True)
    media_type: Mapped[str] = mapped_column(String(20))
    season: Mapped[int] = mapped_column(Integer, default=0)
    episode: Mapped[int] = mapped_column(Integer, default=0)
    position: Mapped[float] = mapped_column(Float, default=0)
    duration: Mapped[float] = mapped_column(Float, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    user: Mapped[User] = relationship()


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "media_id", "media_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    media_id: Mapped[str] = mapped_column(String(100), index=True)
    media_type: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user: Mapped[User] = relationship()


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    discord_instance_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    host_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    current_media: Mapped[str | None] = mapped_column(String(100), nullable=True)
    current_season: Mapped[int] = mapped_column(Integer, default=0)
    current_episode: Mapped[int] = mapped_column(Integer, default=0)
    position: Mapped[float] = mapped_column(Float, default=0)
    state: Mapped[str] = mapped_column(String(20), default="paused")
    playback_rate: Mapped[float] = mapped_column(Float, default=1)
    subtitle: Mapped[str | None] = mapped_column(String(50), nullable=True)
    audio_track: Mapped[str | None] = mapped_column(String(50), nullable=True)
    controllers: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RoomMember(Base):
    __tablename__ = "room_members"
    __table_args__ = (UniqueConstraint("room_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user: Mapped[User] = relationship()


class CustomSource(Base):
    __tablename__ = "custom_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    media_type: Mapped[str] = mapped_column(String(20), index=True)
    media_id: Mapped[str] = mapped_column(String(100), index=True)
    season: Mapped[int] = mapped_column(Integer, default=0)
    episode: Mapped[int] = mapped_column(Integer, default=0)
    provider: Mapped[str] = mapped_column(String(60), default="custom")
    url: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(20))
    language: Mapped[str] = mapped_column(String(20), default="original")
    quality: Mapped[str] = mapped_column(String(20), default="auto")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlaybackSourceCache(Base):
    __tablename__ = "playback_source_cache"
    __table_args__ = (UniqueConstraint("media_id", "season", "episode"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    media_id: Mapped[str] = mapped_column(String(100), index=True)
    season: Mapped[int] = mapped_column(Integer, default=0)
    episode: Mapped[int] = mapped_column(Integer, default=0)
    sources: Mapped[dict | list] = mapped_column(JSON, default=list)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class WatchAvailabilityCache(Base):
    __tablename__ = "watch_availability_cache"

    media_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), default="tmdb")
    sources: Mapped[list] = mapped_column(JSON, default=list)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
