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
from backend.auth import calculate_channel_access
from backend.config import get_settings
from backend.room_manager import RoomManager
from backend.auth import create_access_token, create_websocket_ticket, decode_websocket_ticket, upsert_user
from backend.database import SessionLocal, init_db
from backend.main import app
from backend.models import BrowserEntry, Room


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


def test_websocket_ticket_is_bound_to_room():
    user = SimpleNamespace(discord_id="ws-user", username="WS User", avatar=None)
    ticket = create_websocket_ticket(user, "room-one")
    assert decode_websocket_ticket(ticket, "room-one")["sub"] == "ws-user"
    with pytest.raises(ValueError): decode_websocket_ticket(ticket, "room-two")


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
