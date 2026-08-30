import asyncio
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from backend.browser.security import validate_public_url
from backend.browser.shield import BrowserShield
from backend.browser.publisher import browser_publisher
from backend.browser.settings import browser_setting
from backend.config import get_settings

try:
    from playwright.async_api import async_playwright
except ImportError:  # deployment can expose a degraded health status instead of crashing FastAPI
    async_playwright = None


logger = logging.getLogger("craftplay.browser")


@dataclass
class BrowserRuntime:
    room_id: str
    session_id: str
    context: Any
    page: Any
    shield: BrowserShield
    current_url: str
    profile_path: Path
    started_at: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)
    restarting: bool = False
    console: list[dict] = field(default_factory=list)
    xserver: Any = None


class BrowserService:
    def __init__(self):
        self.settings = get_settings()
        self._playwright = None
        self.sessions: dict[str, BrowserRuntime] = {}
        self.lock = asyncio.Lock()
        self.cleanup_task: asyncio.Task | None = None

    async def startup(self) -> None:
        if async_playwright is not None:
            self._playwright = await async_playwright().start()
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def shutdown(self) -> None:
        if self.cleanup_task:
            self.cleanup_task.cancel()
        for room_id in list(self.sessions):
            await self.close(room_id)
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def status(self) -> dict:
        executable = False
        if self._playwright:
            try:
                executable = Path(self._playwright.chromium.executable_path).exists()
            except Exception:
                executable = False
        return {
            "chromium": "healthy" if executable else "unavailable",
            "playwright": "healthy" if self._playwright else "unavailable",
            "active_sessions": len(self.sessions),
            "max_sessions": self.settings.max_browser_sessions,
            "publisher": browser_publisher.status(),
        }

    async def start(self, room_id: str, session_id: str, url: str, shield_mode: str = "STANDARD") -> BrowserRuntime:
        safe = await validate_public_url(url)
        async with self.lock:
            existing = self.sessions.get(room_id)
            if existing:
                await self.navigate(room_id, safe.url)
                return existing
            if len(self.sessions) >= self.settings.max_browser_sessions:
                raise RuntimeError("Todos os navegadores estao ocupados")
            if not self._playwright:
                raise RuntimeError("Playwright nao esta instalado ou inicializado")
            profile_root = Path(self.settings.browser_profile_root).resolve()
            profile_root.mkdir(parents=True, exist_ok=True)
            profile_path = (profile_root / room_id).resolve()
            if profile_root not in profile_path.parents:
                raise RuntimeError("Identificador de sala invalido")
            profile_path.mkdir(parents=True, exist_ok=True)
            xserver = None
            browser_env = dict(os.environ)
            if os.name != "nt" and not self.settings.browser_headless:
                if not shutil.which("Xvfb"):
                    raise RuntimeError("Xvfb nao esta instalado para o Chromium visual")
                display = f":{100 + len(self.sessions)}"
                xserver = await asyncio.create_subprocess_exec(
                    "Xvfb", display, "-screen", "0", f"{self.settings.browser_width}x{self.settings.browser_height}x24", "-nolisten", "tcp",
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                )
                browser_env["DISPLAY"] = display
                await asyncio.sleep(.2)
            try:
                context = await asyncio.wait_for(
                    self._playwright.chromium.launch_persistent_context(
                        str(profile_path), headless=self.settings.browser_headless,
                        viewport={"width": self.settings.browser_width, "height": self.settings.browser_height},
                        env=browser_env,
                        accept_downloads=False,
                        args=["--disable-dev-shm-usage", "--no-first-run", "--autoplay-policy=no-user-gesture-required"],
                    ), timeout=self.settings.browser_start_timeout,
                )
            except Exception as exc:
                if xserver and xserver.returncode is None: xserver.terminate()
                raise RuntimeError(f"Chromium indisponivel: {type(exc).__name__}") from exc
            page = context.pages[0] if context.pages else await context.new_page()
            shield = BrowserShield(shield_mode, safe.hostname, self.settings.browser_allow_downloads)
            await shield.install(context, page)
            runtime = BrowserRuntime(room_id, session_id, context, page, shield, safe.url, profile_path, xserver=xserver)
            page.on("console", lambda message: self._record_console(runtime, message.type, message.text))
            page.on("crash", lambda: asyncio.create_task(self._recover(runtime)))
            self.sessions[room_id] = runtime
        await self.navigate(room_id, safe.url)
        if runtime.xserver:
            await browser_publisher.start(room_id, f"craftplay-{room_id}", browser_env["DISPLAY"])
        logger.info("[BROWSER] Room %s started Chromium", room_id)
        return runtime

    async def navigate(self, room_id: str, url: str) -> str:
        runtime = self._require(room_id)
        safe = await validate_public_url(url, enforce_allowlist=runtime.shield.mode == "STRICT")
        await runtime.page.goto(safe.url, wait_until="domcontentloaded", timeout=self.settings.browser_start_timeout * 1000)
        # Revalidate the final hostname to mitigate redirects and DNS rebinding.
        final = await validate_public_url(runtime.page.url, enforce_allowlist=runtime.shield.mode == "STRICT")
        runtime.current_url = final.url
        runtime.last_activity = time.monotonic()
        return runtime.current_url

    async def action(self, room_id: str, event: str, payload: dict) -> None:
        runtime = self._require(room_id)
        page = runtime.page
        width, height = self.settings.browser_width, self.settings.browser_height
        if event == "MOUSE_MOVE":
            await page.mouse.move(self._coordinate(payload.get("x"), width), self._coordinate(payload.get("y"), height))
        elif event == "MOUSE_CLICK":
            await page.mouse.click(self._coordinate(payload.get("x"), width), self._coordinate(payload.get("y"), height), click_count=min(2, max(1, int(payload.get("count", 1)))))
        elif event == "MOUSE_SCROLL":
            await page.mouse.wheel(float(payload.get("delta_x", 0)), float(payload.get("delta_y", 0)))
        elif event == "KEY_DOWN":
            await page.keyboard.down(str(payload.get("key", ""))[:40])
        elif event == "KEY_UP":
            await page.keyboard.up(str(payload.get("key", ""))[:40])
        elif event == "TEXT_INPUT":
            await page.keyboard.insert_text(str(payload.get("text", ""))[:2000])
        elif event == "BACK":
            await page.go_back(wait_until="domcontentloaded")
        elif event == "FORWARD":
            await page.go_forward(wait_until="domcontentloaded")
        elif event == "RELOAD":
            await page.reload(wait_until="domcontentloaded")
        elif event == "HOME":
            homepage = browser_setting("homepage", self.settings.browser_homepage)
            if homepage == "about:blank":
                await page.goto("about:blank")
            else:
                await self.navigate(room_id, homepage)
        elif event == "FOCUS":
            await page.bring_to_front()
        else:
            raise ValueError("Evento de navegador desconhecido")
        runtime.current_url = page.url
        runtime.last_activity = time.monotonic()

    async def close(self, room_id: str, *, preserve_profile: bool = False) -> None:
        runtime = self.sessions.pop(room_id, None)
        if not runtime:
            return
        try:
            await browser_publisher.close(room_id)
            await runtime.context.close()
        finally:
            if runtime.xserver and runtime.xserver.returncode is None:
                runtime.xserver.terminate()
            if not preserve_profile and runtime.profile_path.exists():
                await asyncio.to_thread(shutil.rmtree, runtime.profile_path, True)
        logger.info("[BROWSER] Room %s closed Chromium", room_id)

    def debug(self, room_id: str) -> dict:
        runtime = self._require(room_id)
        return {
            "room_id": room_id, "current_url": runtime.current_url,
            "uptime": int(time.monotonic() - runtime.started_at),
            "shield": runtime.shield.status(), "console": runtime.console[-50:],
        }

    def _require(self, room_id: str) -> BrowserRuntime:
        runtime = self.sessions.get(room_id)
        if not runtime:
            raise RuntimeError("Navegador remoto nao esta ativo")
        return runtime

    @staticmethod
    def _coordinate(value, size: int) -> float:
        normalized = min(1.0, max(0.0, float(value)))
        return normalized * size

    @staticmethod
    def _record_console(runtime: BrowserRuntime, level: str, text: str) -> None:
        # URLs and messages only; never request headers, cookies or form values.
        runtime.console.append({"level": level, "message": text[:500]})
        runtime.console = runtime.console[-100:]

    async def _recover(self, runtime: BrowserRuntime) -> None:
        if runtime.restarting:
            return
        runtime.restarting = True
        logger.warning("[BROWSER] Chromium crashed in room %s; one restart will be attempted", runtime.room_id)
        room_id, session_id, url, mode = runtime.room_id, runtime.session_id, runtime.current_url, runtime.shield.mode
        await self.close(room_id)
        try:
            await self.start(room_id, session_id, url, mode)
        except Exception:
            logger.exception("[BROWSER] Chromium restart failed in room %s", room_id)

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            cutoff = time.monotonic() - int(browser_setting("idle_timeout", self.settings.browser_idle_timeout))
            for room_id, runtime in list(self.sessions.items()):
                if runtime.last_activity < cutoff:
                    await self.close(room_id)
                    from backend.browser.state import browser_state_store
                    await browser_state_store.delete(room_id)
                    from datetime import datetime, timezone
                    from sqlalchemy import select
                    from backend.database import SessionLocal
                    from backend.models import BrowserSession
                    with SessionLocal() as db:
                        row = db.scalar(select(BrowserSession).where(BrowserSession.room_id == room_id, BrowserSession.closed_at.is_(None)))
                        if row:
                            row.browser_status = "CLOSED"; row.closed_at = datetime.now(timezone.utc); db.commit()


browser_service = BrowserService()
