from datetime import datetime, timedelta, timezone

import httpx
from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.database import get_db
from backend.models import User


ALGORITHM = "HS256"


def create_access_token(user: User) -> str:
    settings = get_settings()
    payload = {
        "sub": user.discord_id,
        "name": user.username,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


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
    authorization: str | None = Header(default=None),
    x_discord_user_id: str | None = Header(default=None),
    x_discord_username: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    settings = get_settings()
    discord_id = None
    username = None
    if authorization and authorization.startswith("Bearer "):
        try:
            payload = jwt.decode(authorization[7:], settings.secret_key, algorithms=[ALGORITHM])
            discord_id = payload.get("sub")
            username = payload.get("name")
        except JWTError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão inválida") from exc
    elif settings.environment != "production":
        discord_id = x_discord_user_id or "local-user"
        username = x_discord_username or "Visitante local"
    if not discord_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticação do Discord necessária")
    return upsert_user(db, str(discord_id), str(username or "Usuário Discord"))


async def exchange_discord_code(code: str) -> dict:
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
