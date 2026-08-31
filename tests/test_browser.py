from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from jose import jwt
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.browser.api import slugify
from backend.browser.livekit import create_viewer_token
from backend.browser.security import _is_public_address, same_site, validate_public_url
from backend.browser.service import BrowserService
from backend.browser.shield import BrowserShield
from backend.auth import calculate_channel_access, verify_dashboard_access
from backend.config import get_settings
from backend.room_manager import RoomManager
from backend.auth import create_access_token, create_websocket_ticket, decode_websocket_ticket, upsert_user
from backend.config import Settings
from backend.database import SessionLocal, init_db
from backend.main import app
from backend.models import BrowserEntry, BrowserSession, Room


def test_ssrf_rejects_private_and_metadata_addresses():
    for address in ["127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1", "169.254.169.254", "::1"]:
        assert not _is_public_address(address)
    assert _is_public_address("1.1.1.1")


@pytest.mark.asyncio
async def test_ssrf_rejects_unsafe_schemes_and_credentials():
    with pytest.raises(ValueError): await validate_public_url("file:///etc/passwd")
    with pytest.raises(ValueError): await validate_public_url("gopher://example.com")
    with pytest.raises(ValueError): await validate_public_url("https://user:pass@example.com")


@pytest.mark.asyncio
async def test_ssrf_rejects_private_dns_resolution(monkeypatch):
    monkeypatch.setattr("backend.browser.security.socket.getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", ("10.20.30.40", 443))])
    with pytest.raises(ValueError, match="rede privada"):
        await validate_public_url("https://example.test")


@pytest.mark.asyncio
async def test_public_dns_resolution_is_accepted(monkeypatch):
    monkeypatch.setattr("backend.browser.security.socket.getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))])
    result = await validate_public_url("https://example.test/path")
    assert result.hostname == "example.test"
    assert result.addresses == ("93.184.216.34",)


def test_navigation_same_site_rules():
    assert same_site("video.example.com", "example.com")
    assert same_site("example.com", "video.example.com")
    assert not same_site("example.net", "example.com")


def test_discord_channel_permission_respects_overwrites():
    guild = {"id": "guild", "roles": [{"id": "guild", "permissions": str(1 << 10)}, {"id": "role", "permissions": "0"}]}
    member = {"roles": ["role"]}
    denied = {"guild_id": "guild", "permission_overwrites": [{"id": "guild", "type": 0, "allow": "0", "deny": str(1 << 10)}]}
    allowed = {"guild_id": "guild", "permission_overwrites": [
        {"id": "guild", "type": 0, "allow": "0", "deny": str(1 << 10)},
        {"id": "role", "type": 0, "allow": str(1 << 10), "deny": "0"},
    ]}
    assert not calculate_channel_access(member, guild, denied, "user")
    assert calculate_channel_access(member, guild, allowed, "user")


def test_discord_allowed_role_and_administrator_are_accepted():
    channel = {"permission_overwrites": []}
    assert calculate_channel_access({"roles": ["staff"]}, {"roles": []}, channel, "user", ["staff"])
    assert calculate_channel_access({"roles": ["admin"]}, {"roles": [{"id": "admin", "permissions": str(1 << 3)}]}, channel, "user")


@pytest.mark.asyncio
async def test_dashboard_explicit_user_id_does_not_require_guild_or_channel(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "dashboard_allowed_user_ids", ["123456789"])
    monkeypatch.setattr(settings, "discord_bot_token", "")
    monkeypatch.setattr(settings, "discord_guild_id", "")
    monkeypatch.setattr(settings, "dashboard_channel_id", "")
    assert await verify_dashboard_access("123456789") is True


def test_dashboard_user_ids_accept_comma_separated_env_value():
    settings = Settings(_env_file=None, dashboard_allowed_user_ids="123, 456")
    assert settings.dashboard_allowed_user_ids == ["123", "456"]


def test_dashboard_user_ids_tolerate_quotes_and_json_brackets():
    settings = Settings(_env_file=None, dashboard_allowed_user_ids='["123", "456"]')
    assert settings.dashboard_allowed_user_ids == ["123", "456"]


def test_authenticated_allowlisted_user_can_claim_dashboard_token(monkeypatch):
    init_db()
    suffix = __import__("uuid").uuid4().hex
    discord_id = f"claim-{suffix}"
    with SessionLocal() as db:
        user = upsert_user(db, discord_id, "Dashboard Owner")
        token = create_access_token(user)
    settings = get_settings()
    monkeypatch.setattr(settings, "dashboard_allowed_user_ids", [discord_id])
    with TestClient(app) as client:
        claimed = client.post("/api/auth/dashboard", headers={"Authorization": f"Bearer {token}"})
        assert claimed.status_code == 200, claimed.text
        admin_token = claimed.json()["access_token"]
        dashboard = client.get(
            "/api/dashboard/browser/entries",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert dashboard.status_code == 200, dashboard.text


def test_entry_slug_is_stable_and_ascii():
    assert slugify("Séries & Animes 2026") == "series-animes-2026"


def test_coordinates_are_normalized():
    assert BrowserService._coordinate(-1, 1920) == 0
    assert BrowserService._coordinate(.5, 1920) == 960
    assert BrowserService._coordinate(2, 1080) == 1080


def test_input_rate_limit_blocks_flood():
    manager = RoomManager()
    assert all(manager._within_rate_limit("room", "user", "MOUSE_SCROLL") for _ in range(30))
    assert not manager._within_rate_limit("room", "user", "MOUSE_SCROLL")


@pytest.mark.asyncio
async def test_shield_blocks_advertising_request():
    shield = BrowserShield("STANDARD", "example.com")
    calls = []
    route = SimpleNamespace(request=SimpleNamespace(url="https://doubleclick.net/ad.js", resource_type="script"), abort=lambda reason: calls.append(reason))
    async def abort(reason): calls.append(reason)
    route.abort = abort
    await shield._route(route)
    assert calls == ["blockedbyclient"]
    assert shield.status()["ads"] == 1


@pytest.mark.asyncio
async def test_shield_cancels_download_by_default():
    shield = BrowserShield("STANDARD", "example.com", allow_downloads=False)
    cancelled = []
    class Download:
        url = "https://example.com/file.exe"
        async def cancel(self): cancelled.append(True)
    shield._schedule_download_cancel(Download())
    await __import__("asyncio").sleep(0)
    assert cancelled
    assert shield.status()["downloads"] == 1


def test_livekit_viewer_token_cannot_publish(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "livekit_url", "wss://livekit.example")
    monkeypatch.setattr(settings, "livekit_api_key", "key")
    monkeypatch.setattr(settings, "livekit_api_secret", "secret")
    token = create_viewer_token("room", "user", "User")
    payload = jwt.decode(token, "secret", algorithms=["HS256"], audience=None, options={"verify_aud": False})
    assert payload["video"]["roomJoin"] is True
    assert payload["video"]["canSubscribe"] is True
    assert payload["video"]["canPublish"] is False


def test_browser_entry_crud_requires_admin_and_persists(monkeypatch):
    init_db()
    async def safe(url, **kwargs): return SimpleNamespace(url=url, hostname="example.com", addresses=("93.184.216.34",))
    monkeypatch.setattr("backend.browser.api.validate_public_url", safe)
    with SessionLocal() as db:
        user = upsert_user(db, "browser-admin-test", "Browser Admin")
        token = create_access_token(user, dashboard_admin=True)
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        denied = client.get("/api/dashboard/browser/entries")
        assert denied.status_code == 401
        created = client.post("/api/dashboard/browser/entries", headers=headers, json={
            "name": "CRUD Browser Test", "url": "https://example.com/test", "entry_type": "website",
            "category": "sites", "shield_mode": "STANDARD", "open_mode": "browser",
        })
        assert created.status_code == 201, created.text
        entry_id = created.json()["id"]
        updated = client.patch(f"/api/dashboard/browser/entries/{entry_id}", headers=headers, json={"featured": True})
        assert updated.status_code == 200 and updated.json()["featured"] is True
        deleted = client.delete(f"/api/dashboard/browser/entries/{entry_id}", headers=headers)
        assert deleted.status_code == 204
    with SessionLocal() as db:
        assert db.get(BrowserEntry, entry_id) is None


def test_closed_browser_session_is_reopened_instead_of_duplicated(monkeypatch):
    init_db()
    suffix = __import__("uuid").uuid4().hex
    with SessionLocal() as db:
        user = upsert_user(db, f"reopen-user-{suffix}", "Reopen Host")
        room = Room(discord_instance_id=f"reopen-room-{suffix}", host_user_id=user.id)
        entry = BrowserEntry(
            name="Reopen Test",
            slug=f"reopen-{suffix}",
            url="https://example.com/reopen",
            entry_type="website",
            category="sites",
        )
        db.add_all([room, entry])
        db.flush()
        closed = BrowserSession(
            room_id=room.id,
            host_user_id=user.id,
            current_url="https://example.com/old",
            stream_room_name=f"craftplay-{room.id}",
            browser_status="CLOSED",
            closed_at=datetime.now(timezone.utc),
        )
        db.add(closed)
        db.commit()
        token = create_access_token(user)
        room_id, entry_id, session_id = room.id, entry.id, closed.id

    async def safe(url, **_kwargs):
        return SimpleNamespace(url=url, hostname="example.com", addresses=("93.184.216.34",))

    async def start(_room_id, _session_id, url, _shield_mode):
        return SimpleNamespace(current_url=url)

    monkeypatch.setattr("backend.browser.api.validate_public_url", safe)
    monkeypatch.setattr("backend.browser.api.browser_service.start", start)
    with TestClient(app) as client:
        response = client.post(
            "/api/browser/session/start",
            headers={"Authorization": f"Bearer {token}"},
            json={"room_id": room_id, "entry_id": entry_id},
        )
    assert response.status_code == 200, response.text
    assert response.json()["id"] == session_id
    assert response.json()["browser_status"] == "READY"
    with SessionLocal() as db:
        rows = db.scalars(select(BrowserSession).where(BrowserSession.room_id == room_id)).all()
        assert len(rows) == 1
        assert rows[0].closed_at is None


def test_websocket_ticket_is_bound_to_room():
    user = SimpleNamespace(discord_id="ws-user", username="WS User", avatar=None)
    ticket = create_websocket_ticket(user, "room-one")
    assert decode_websocket_ticket(ticket, "room-one")["sub"] == "ws-user"
    with pytest.raises(ValueError): decode_websocket_ticket(ticket, "room-two")


def test_development_headers_are_never_accepted_on_public_hosts():
    with TestClient(app, base_url="https://public.example") as client:
        response = client.get("/api/browser/entries", headers={"X-Discord-User-Id": "impersonated", "X-Discord-Username": "Host"})
        assert response.status_code == 401


def test_direct_browser_login_starts_discord_oauth_without_open_redirect():
    with TestClient(app, base_url="https://public.example", follow_redirects=False) as client:
        response = client.get("/auth/discord/user/login?next=https://evil.example")
        assert response.status_code in {302, 307}
        assert response.headers["location"].startswith("https://discord.com/oauth2/authorize?")
        assert client.cookies.get("craftplay_oauth_purpose") == "user"
        assert client.cookies.get("craftplay_oauth_next").strip('"') == "/"


def test_invalid_optional_browser_headless_does_not_crash_settings():
    settings = Settings(_env_file=None, browser_headless="falsev")
    assert settings.browser_headless is False


def test_database_fallback_has_safe_local_default():
    settings = Settings(_env_file=None)
    assert settings.database_fallback_url.startswith("sqlite:///")


def test_livekit_http_url_is_normalized_for_websocket_clients():
    settings = Settings(_env_file=None, livekit_url="https://project.livekit.cloud/")
    assert settings.livekit_url == "wss://project.livekit.cloud"


@pytest.mark.asyncio
async def test_room_participant_limit_is_atomic(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "room_max_participants", 1)
    with SessionLocal() as db:
        host = upsert_user(db, "limit-host", "Limit Host")
        room = Room(discord_instance_id="limit-test-instance", host_user_id=host.id)
        existing = db.scalar(select(Room).where(Room.discord_instance_id == "limit-test-instance"))
        if existing: room = existing
        else: db.add(room); db.commit(); db.refresh(room)
    class Socket:
        async def accept(self): pass
        async def send_json(self, payload): pass
    manager = RoomManager()
    await manager.connect(room.id, "limit-host", Socket(), {"username": "Host"})
    with pytest.raises(OverflowError):
        await manager.connect(room.id, "limit-guest", Socket(), {"username": "Guest"})


@pytest.mark.asyncio
async def test_headless_browser_emits_websocket_screencast(monkeypatch):
    from backend.room_manager import room_manager

    service = BrowserService()
    monkeypatch.setattr(service.settings, "browser_headless", True)
    monkeypatch.setattr(service.settings, "browser_websocket_fallback", True)
    monkeypatch.setattr(service.settings, "browser_auto_install", False)
    await service.startup()
    if not service._chromium_available():
        await service.shutdown()
        pytest.skip("Chromium local não instalado")
    safe = SimpleNamespace(url="https://example.com", hostname="example.com")

    async def fake_validate(*_args, **_kwargs):
        return safe

    frames = []

    async def capture_frame(_room_id, payload):
        frames.append(payload)

    monkeypatch.setattr("backend.browser.service.validate_public_url", fake_validate)
    monkeypatch.setattr(room_manager, "broadcast_browser_frame", capture_frame)
    try:
        runtime = await service.start("frame-room", "frame-session", "https://example.test")
        await runtime.page.set_content("<main style='background:#123;color:white'>CraftPlay screencast</main>")
        captured = await service.capture_frame("frame-room")
        assert captured["event"] == "BROWSER_FRAME" and captured["data"]
        for _ in range(30):
            if frames:
                break
            await __import__("asyncio").sleep(.1)
        assert frames and frames[0]["event"] == "BROWSER_FRAME"
        assert frames[0]["data"]
    finally:
        await service.close("frame-room")
        await service.shutdown()
