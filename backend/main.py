import os
import logging
import secrets
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Cookie, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.api import router
from backend.auth import create_access_token, decode_websocket_ticket, exchange_discord_code, upsert_user, verify_dashboard_access
from backend.browser import browser_service
from backend.browser.state import browser_state_store
from backend.browser.api import dashboard_router, router as browser_router
from backend.config import get_settings
from backend.database import SessionLocal, init_db
from backend.room_manager import room_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await browser_state_store.startup()
    await browser_service.startup()
    try:
        yield
    finally:
        await browser_service.shutdown()
        await browser_state_store.shutdown()


settings = get_settings()
logger = logging.getLogger("craftplay.websocket")
app = FastAPI(title="CraftPlay API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Discord-User-Id", "X-Discord-Username", "X-Admin-Key"],
)
app.include_router(router)
app.include_router(browser_router)
app.include_router(dashboard_router)


@app.get("/auth/discord/login", include_in_schema=False)
async def dashboard_login():
    if not settings.discord_client_id:
        raise HTTPException(status_code=503, detail="Discord OAuth nao configurado")
    state = secrets.token_urlsafe(32)
    query = urlencode({
        "client_id": settings.discord_client_id,
        "response_type": "code",
        "redirect_uri": settings.discord_redirect_uri,
        "scope": "identify",
        "state": state,
        "prompt": "none",
    })
    response = RedirectResponse(f"https://discord.com/oauth2/authorize?{query}")
    response.set_cookie("craftplay_oauth_state", state, max_age=600, httponly=True, secure=True, samesite="lax")
    return response


@app.get("/auth/discord/callback", include_in_schema=False)
async def dashboard_callback(code: str, state: str, craftplay_oauth_state: str | None = Cookie(default=None)):
    if not craftplay_oauth_state or not secrets.compare_digest(state, craftplay_oauth_state):
        raise HTTPException(status_code=400, detail="Estado OAuth invalido")
    oauth = await exchange_discord_code(code, settings.discord_redirect_uri)
    profile = oauth["profile"]
    if not await verify_dashboard_access(str(profile["id"])):
        raise HTTPException(status_code=403, detail="Voce nao possui acesso ao canal do dashboard")
    avatar = f"https://cdn.discordapp.com/avatars/{profile['id']}/{profile['avatar']}.png" if profile.get("avatar") else None
    with SessionLocal() as db:
        user = upsert_user(db, str(profile["id"]), profile.get("global_name") or profile["username"], avatar)
        token = create_access_token(user, dashboard_admin=True)
    response = RedirectResponse("/dashboard")
    response.delete_cookie("craftplay_oauth_state")
    response.set_cookie("craftplay_dashboard", token, max_age=7 * 86400, httponly=True, secure=True, samesite="lax")
    return response


@app.websocket("/ws/room/{room_id}")
async def room_socket(websocket: WebSocket, room_id: str):
    await websocket.accept()
    try:
        authentication = await asyncio.wait_for(websocket.receive_json(), timeout=5)
    except Exception:
        await websocket.close(code=4401, reason="Autenticacao necessaria")
        return
    ticket = str(authentication.get("ticket", "")) if authentication.get("event") == "AUTH" else ""
    if ticket:
        try:
            identity = decode_websocket_ticket(ticket, room_id)
        except ValueError:
            await websocket.close(code=4401, reason="Ticket invalido")
            return
        discord_id = str(identity["sub"])
        username = str(identity.get("name") or "Participante")[:100]
        avatar = identity.get("avatar")
    elif settings.environment != "production":
        discord_id = str(authentication.get("user_id", ""))
        username = str(authentication.get("username", "Participante"))[:100]
        avatar = authentication.get("avatar")
    else:
        await websocket.close(code=4401, reason="Ticket necessario")
        return
    if not discord_id:
        await websocket.close(code=4401, reason="Usuário ausente")
        return
    try:
        await room_manager.connect(room_id, discord_id, websocket, {"discord_id": discord_id, "username": username, "avatar": avatar}, already_accepted=True)
        while True:
            payload = await websocket.receive_json()
            if payload.get("room_id") not in {None, room_id}:
                await websocket.send_json({"event": "ERROR", "message": "Sala inválida"})
                continue
            await room_manager.handle(room_id, discord_id, payload)
    except WebSocketDisconnect:
        await room_manager.disconnect(room_id, discord_id)
    except ValueError:
        await websocket.close(code=4404, reason="Sala não encontrada")
    except PermissionError as exc:
        await websocket.close(code=4403, reason=str(exc))
    except OverflowError as exc:
        await websocket.close(code=4409, reason=str(exc))
    except Exception:
        logger.exception("Falha no WebSocket da sala %s para o usuário %s", room_id, discord_id)
        await room_manager.disconnect(room_id, discord_id)
    finally:
        room_manager.release_pending(room_id, discord_id)


FRONTEND = Path(__file__).resolve().parents[1] / "public"
if FRONTEND.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        candidate = (FRONTEND / path).resolve()
        if path and candidate.is_file() and FRONTEND.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
