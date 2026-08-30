import json

from backend.config import get_settings

try:
    import redis.asyncio as redis
except ImportError:
    redis = None


class BrowserStateStore:
    def __init__(self):
        self.client = None
        self.memory: dict[str, dict] = {}

    async def startup(self) -> None:
        url = get_settings().redis_url
        if redis and url:
            candidate = None
            try:
                candidate = redis.from_url(url, decode_responses=True)
                await candidate.ping()
                self.client = candidate
            except Exception:
                if candidate: await candidate.aclose()

    async def shutdown(self) -> None:
        if self.client: await self.client.aclose()
        self.client = None

    async def put(self, room_id: str, state: dict) -> None:
        self.memory[room_id] = state
        if self.client:
            try: await self.client.set(f"craftplay:room:{room_id}", json.dumps(state, default=str), ex=86400)
            except Exception: await self._fallback()

    async def get(self, room_id: str) -> dict | None:
        if self.client:
            try:
                value = await self.client.get(f"craftplay:room:{room_id}")
                if value: return json.loads(value)
            except Exception: await self._fallback()
        return self.memory.get(room_id)

    async def delete(self, room_id: str) -> None:
        self.memory.pop(room_id, None)
        if self.client:
            try: await self.client.delete(f"craftplay:room:{room_id}")
            except Exception: await self._fallback()

    async def _fallback(self) -> None:
        client, self.client = self.client, None
        if client:
            try: await client.aclose()
            except Exception: pass

    @property
    def backend(self) -> str:
        return "redis" if self.client else "memory"


browser_state_store = BrowserStateStore()
