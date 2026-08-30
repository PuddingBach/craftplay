import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api import router
from backend.config import get_settings
from backend.database import init_db
from backend.room_manager import room_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


settings = get_settings()
logger = logging.getLogger("craftplay.websocket")
app = FastAPI(title="CraftPlay API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Discord-User-Id", "X-Discord-Username"],
)
app.include_router(router)


@app.websocket("/ws/room/{room_id}")
async def room_socket(websocket: WebSocket, room_id: str):
    discord_id = websocket.query_params.get("user_id", "")
    username = websocket.query_params.get("username", "Participante")[:100]
    avatar = websocket.query_params.get("avatar")
    if not discord_id:
        await websocket.close(code=4401, reason="Usuário ausente")
        return
    try:
        await room_manager.connect(room_id, discord_id, websocket, {"discord_id": discord_id, "username": username, "avatar": avatar})
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
    except Exception:
        logger.exception("Falha no WebSocket da sala %s para o usuário %s", room_id, discord_id)
        await room_manager.disconnect(room_id, discord_id)


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
