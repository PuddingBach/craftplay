from collections.abc import Generator
import logging

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import get_settings


class Base(DeclarativeBase):
    pass


logger = logging.getLogger(__name__)
settings = get_settings()


def _create_engine(url: str):
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


engine = _create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
_database_backend = "sqlite" if settings.database_url.startswith("sqlite") else "postgresql"
_database_degraded = False


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _create_schema() -> None:
    from backend import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    from backend.migrations import apply_migrations
    with SessionLocal() as db:
        apply_migrations(db)


def init_db() -> None:
    global engine, _database_backend, _database_degraded
    try:
        _create_schema()
        return
    except OperationalError as exc:
        if settings.database_url.startswith("sqlite"):
            raise
        logger.error(
            "PostgreSQL indisponivel; iniciando com SQLite local em modo degradado (erro=%s)",
            type(exc.orig).__name__ if exc.orig else type(exc).__name__,
        )
    previous_engine = engine
    engine = _create_engine(settings.database_fallback_url)
    SessionLocal.configure(bind=engine)
    previous_engine.dispose()
    _database_backend = "sqlite-fallback"
    _database_degraded = True
    _create_schema()


def database_status() -> dict[str, str | bool]:
    return {"backend": _database_backend, "degraded": _database_degraded}
