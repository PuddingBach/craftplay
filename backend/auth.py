from datetime import datetime, timedelta, timezone

import httpx
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.database import get_db
from backend.models import User


ALGORITHM = "HS256"


def create_access_token(user: User, *, dashboard_admin: bool = False) -> str:
    settings = get_settings()
    payload = {
        "sub": user.discord_id,
        "name": user.username,
        "dashboard_admin": dashboard_admin,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_websocket_ticket(user: User, room_id: str) -> str:
    settings = get_settings()
    return jwt.encode({
        "sub": user.discord_id, "name": user.username, "avatar": user.avatar,
        "room_id": room_id, "kind": "room_websocket",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }, settings.secret_key, algorithm=ALGORITHM)


def decode_websocket_ticket(ticket: str, room_id: str) -> dict:
    try:
        payload = jwt.decode(ticket, get_settings().secret_key, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError("Ticket WebSocket invalido") from exc
    if payload.get("kind") != "room_websocket" or payload.get("room_id") != room_id or not payload.get("sub"):
        raise ValueError("Ticket WebSocket invalido")
    return payload


def upsert_user(db: Session, discord_id: str, username: str, avatar: str | None = None) -> User:
    user = db.scalar(select(User).where(User.discord_id == discord_id))
    if user:
        user.username = username
        user.avatar = avatar
    else:
        user = User(discord_id=discord_id, username=username, avatar=avatar)
        db.add(user)
    db.commit()
    db.refresh(user)
    return user


def current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    craftplay_dashboard: str | None = Cookie(default=None),
    x_discord_user_id: str | None = Header(default=None),
    x_discord_username: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    settings = get_settings()
    discord_id = None
    username = None
    raw_token = authorization[7:] if authorization and authorization.startswith("Bearer ") else craftplay_dashboard
    if raw_token:
        try:
            payload = jwt.decode(raw_token, settings.secret_key, algorithms=[ALGORITHM])
            discord_id = payload.get("sub")
            username = payload.get("name")
        except JWTError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão inválida") from exc
    local_host = (request.url.hostname or "").casefold() in {"localhost", "127.0.0.1", "::1", "testserver"}
    if not raw_token and settings.environment != "production" and local_host:
        discord_id = x_discord_user_id or "local-user"
        username = x_discord_username or "Visitante local"
    if not discord_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticação do Discord necessária")
    # Frame polling is frequent; do not update and commit the same user on
    # every authenticated request. Login flows already refresh profile data.
    user = db.scalar(select(User).where(User.discord_id == str(discord_id)))
    if user:
        return user
    return upsert_user(db, str(discord_id), str(username or "Usuário Discord"))


def current_dashboard_admin(
    authorization: str | None = Header(default=None),
    craftplay_dashboard: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    settings = get_settings()
    raw_token = craftplay_dashboard or (authorization[7:] if authorization and authorization.startswith("Bearer ") else None)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Login administrativo necessario")
    try:
        payload = jwt.decode(raw_token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Sessao administrativa invalida") from exc
    if not payload.get("dashboard_admin"):
        raise HTTPException(status_code=403, detail="Acesso ao dashboard negado")
    user = db.scalar(select(User).where(User.discord_id == str(payload.get("sub", ""))))
    if not user:
        raise HTTPException(status_code=401, detail="Usuario nao encontrado")
    return user


async def exchange_discord_code(code: str, redirect_uri: str | None = None) -> dict:
    settings = get_settings()
    if not settings.discord_client_id or not settings.discord_client_secret:
        raise HTTPException(status_code=503, detail="Credenciais do Discord não configuradas")
    async with httpx.AsyncClient(timeout=12) as client:
        token_response = await client.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": settings.discord_client_id,
                "client_secret": settings.discord_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                **({"redirect_uri": redirect_uri} if redirect_uri else {}),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_response.is_error:
            raise HTTPException(status_code=401, detail="O Discord recusou o código de autorização")
        oauth = token_response.json()
        user_response = await client.get(
            "https://discord.com/api/users/@me",
            headers={"Authorization": f"Bearer {oauth['access_token']}"},
        )
        user_response.raise_for_status()
        return {"profile": user_response.json(), "access_token": oauth["access_token"]}


async def verify_dashboard_access(discord_user_id: str) -> bool:
    """Allow explicit user IDs or verify effective VIEW_CHANNEL through the bot API."""
    import asyncio

    settings = get_settings()
    if str(discord_user_id).strip() in settings.dashboard_allowed_user_ids:
        return True
    if not settings.discord_bot_token or not settings.discord_guild_id or not settings.dashboard_channel_id:
        raise HTTPException(
            status_code=503,
            detail="Configure DASHBOARD_ALLOWED_USER_IDS ou as permissoes de canal do dashboard",
        )
    headers = {"Authorization": f"Bot {settings.discord_bot_token}"}
    base = "https://discord.com/api/v10"
    async with httpx.AsyncClient(timeout=12, headers=headers) as client:
        member_response, guild_response, channel_response = await asyncio.gather(
            client.get(f"{base}/guilds/{settings.discord_guild_id}/members/{discord_user_id}"),
            client.get(f"{base}/guilds/{settings.discord_guild_id}"),
            client.get(f"{base}/channels/{settings.dashboard_channel_id}"),
        )
    if member_response.status_code == 404:
        return False
    if not member_response.is_success or not guild_response.is_success or not channel_response.is_success:
        raise HTTPException(status_code=502, detail="Discord indisponivel para validar permissoes")
    member, guild, channel = member_response.json(), guild_response.json(), channel_response.json()
    if str(channel.get("guild_id")) != str(settings.discord_guild_id):
        return False
    return calculate_channel_access(member, guild, channel, discord_user_id, settings.dashboard_allowed_role_ids)


def calculate_channel_access(member: dict, guild: dict, channel: dict, discord_user_id: str, allowed_role_ids: list[str] | None = None) -> bool:
    """Apply Discord's role/overwrite order to determine effective VIEW_CHANNEL."""
    member_roles = {str(role_id) for role_id in member.get("roles", [])}
    if set(allowed_role_ids or []) & member_roles:
        return True

    guild_id = str(channel.get("guild_id") or guild.get("id", ""))
    roles = {str(role["id"]): int(role.get("permissions", "0")) for role in guild.get("roles", [])}
    permissions = roles.get(guild_id, 0)
    for role_id in member_roles:
        permissions |= roles.get(role_id, 0)
    administrator = 1 << 3
    view_channel = 1 << 10
    if permissions & administrator:
        return True
    overwrites = channel.get("permission_overwrites", [])
    everyone = next((item for item in overwrites if str(item.get("id")) == guild_id), None)
    if everyone:
        permissions &= ~int(everyone.get("deny", "0"))
        permissions |= int(everyone.get("allow", "0"))
    role_denies = role_allows = 0
    for item in overwrites:
        if int(item.get("type", 0)) == 0 and str(item.get("id")) in member_roles:
            role_denies |= int(item.get("deny", "0"))
            role_allows |= int(item.get("allow", "0"))
    permissions = (permissions & ~role_denies) | role_allows
    member_overwrite = next((item for item in overwrites if int(item.get("type", 0)) == 1 and str(item.get("id")) == discord_user_id), None)
    if member_overwrite:
        permissions &= ~int(member_overwrite.get("deny", "0"))
        permissions |= int(member_overwrite.get("allow", "0"))
    return bool(permissions & view_channel)
