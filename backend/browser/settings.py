from backend.database import SessionLocal
from backend.models import BrowserSetting


def browser_setting(key: str, default=None):
    try:
        with SessionLocal() as db:
            row = db.get(BrowserSetting, key)
            return row.value if row is not None else default
    except Exception:
        return default
