from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models import BrowserEntry, SchemaMigration


MIGRATION = "20260830_01_shared_browser"


def apply_migrations(db: Session) -> None:
    """Apply additive, idempotent data migrations after metadata creates new tables."""
    if db.get(SchemaMigration, MIGRATION):
        return
    if not (db.scalar(select(func.count()).select_from(BrowserEntry)) or 0):
        db.add_all([
            BrowserEntry(name="YouTube", slug="youtube", entry_type="website", category="sites", url="https://www.youtube.com/", icon_url="https://www.youtube.com/favicon.ico", featured=True, pinned=True, shield_mode="STANDARD", trust_level="official"),
            BrowserEntry(name="Crunchyroll", slug="crunchyroll", entry_type="website", category="animes", url="https://www.crunchyroll.com/pt-br/", icon_url="https://www.crunchyroll.com/favicon.ico", featured=True, shield_mode="STANDARD", trust_level="official"),
            BrowserEntry(name="Blender Open Movies", slug="blender-open-movies", entry_type="website", category="filmes", url="https://studio.blender.org/films/", featured=True, shield_mode="STANDARD", trust_level="official"),
        ])
    db.add(SchemaMigration(version=MIGRATION))
    db.commit()
