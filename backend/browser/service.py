import asyncio
import base64
import logging
import os
import shutil
import sys
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
    cdp: Any = None
    last_frame_at: float = 0
    last_frame_data: bytes | None = None


class BrowserService:
    def __init__(self):
        self.settings = get_settings()
        self._playwright = None
        self.sessions: dict[str, BrowserRuntime] = {}
        self.lock = asyncio.Lock()
        self.cleanup_task: asyncio.Task | None = None
        self.install_task: asyncio.Task | None = None
        self.install_process = None
        self.install_status = "idle"
        self.install_error = ""
        self.launch_ready = False
        memory_limit = self._memory_limit_mb()
        self.max_sessions = 1 if memory_limit and memory_limit <= 2048 else self.settings.max_browser_sessions
        self.viewport_width = min(1280, self.settings.browser_width) if memory_limit and memory_limit <= 2048 else self.settings.browser_width
        self.viewport_height = min(720, self.settings.browser_height) if memory_limit and memory_limit <= 2048 else self.settings.browser_height

    async def startup(self) -> None:
        if async_playwright is not None:
            self._playwright = await async_playwright().start()
            if not self._chromium_available() and self.settings.browser_auto_install:
                self.install_task = asyncio.create_task(self._install_chromium())
            elif self._chromium_available():
                self.install_task = asyncio.create_task(self._probe_chromium())
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def shutdown(self) -> None:
        if self.cleanup_task:
            self.cleanup_task.cancel()
        if self.install_task and not self.install_task.done():
            self.install_task.cancel()
        if self.install_process and self.install_process.returncode is None:
            self.install_process.terminate()
        for room_id in list(self.sessions):
            await self.close(room_id)
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def status(self) -> dict:
        executable = self._chromium_available() and self.launch_ready
        return {
            "chromium": "healthy" if executable else "unavailable",
            "chromium_install": self.install_status,
            "chromium_install_error": self.install_error,
            "playwright": "healthy" if self._playwright else "unavailable",
            "active_sessions": len(self.sessions),
            "max_sessions": self.max_sessions,
            "publisher": browser_publisher.status(),
        }

    async def start(self, room_id: str, session_id: str, url: str, shield_mode: str = "STANDARD") -> BrowserRuntime:
        safe = await validate_public_url(url)
        async with self.lock:
            existing = self.sessions.get(room_id)
            if existing:
                await self.navigate(room_id, safe.url)
                return existing
            if len(self.sessions) >= self.max_sessions:
                raise RuntimeError("Todos os navegadores estao ocupados")
            if not self._playwright:
                raise RuntimeError("Playwright nao esta instalado ou inicializado")
            if not self.launch_ready and self.install_task:
                try:
                    await asyncio.wait_for(asyncio.shield(self.install_task), timeout=self.settings.browser_start_timeout)
                except TimeoutError as exc:
                    raise RuntimeError("Chromium ainda esta sendo preparado; tente novamente em instantes") from exc
            if not self._chromium_available() or not self.launch_ready:
                reason = f": {self.install_error}" if self.install_error else ""
                raise RuntimeError(f"Chromium nao esta instalado{reason}")
            profile_root = Path(self.settings.browser_profile_root).resolve()
            profile_root.mkdir(parents=True, exist_ok=True)
            profile_path = (profile_root / room_id).resolve()
            if profile_root not in profile_path.parents:
                raise RuntimeError("Identificador de sala invalido")
            profile_path.mkdir(parents=True, exist_ok=True)
            xserver = None
            browser_env = dict(os.environ)
            use_headless = self.settings.browser_headless
            if os.name != "nt" and not use_headless and not shutil.which("Xvfb"):
                if self.settings.browser_websocket_fallback:
                    use_headless = True
                    logger.warning("[BROWSER] Xvfb ausente; usando Chromium headless com screencast")
                else:
                    raise RuntimeError("Xvfb nao esta instalado para o Chromium visual")
            if os.name != "nt" and not use_headless:
                if not shutil.which("Xvfb"):
                    raise RuntimeError("Xvfb nao esta instalado para o Chromium visual")
                display = f":{100 + len(self.sessions)}"
                xserver = await asyncio.create_subprocess_exec(
                    "Xvfb", display, "-screen", "0", f"{self.viewport_width}x{self.viewport_height}x24", "-nolisten", "tcp",
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                )
                browser_env["DISPLAY"] = display
                await asyncio.sleep(.2)
            try:
                context = await asyncio.wait_for(
                    self._playwright.chromium.launch_persistent_context(
                        str(profile_path), headless=use_headless,
                        viewport={"width": self.viewport_width, "height": self.viewport_height},
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
        elif self.settings.browser_websocket_fallback:
            await self._start_screencast(runtime)
        logger.info("[BROWSER] Room %s started Chromium", room_id)
        return runtime

    def _chromium_available(self) -> bool:
        if not self._playwright:
            return False
        try:
            return Path(self._playwright.chromium.executable_path).exists()
        except Exception:
            return False

    async def _install_chromium(self) -> None:
        self.install_status = "installing"
        logger.info("[BROWSER] Instalando Chromium em segundo plano")
        try:
            self.install_process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "playwright", "install", "chromium",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(self.install_process.communicate(), timeout=600)
            if self.install_process.returncode != 0 or not self._chromium_available():
                detail = (stderr or stdout).decode("utf-8", "replace").strip().splitlines()
                raise RuntimeError(detail[-1][:300] if detail else "download nao concluiu")
            await self._probe_chromium()
        except asyncio.CancelledError:
            self.install_status = "cancelled"
            raise
        except Exception as exc:
            if self.install_process and self.install_process.returncode is None:
                self.install_process.terminate()
            self.install_status = "failed"
            self.install_error = f"{type(exc).__name__}: {str(exc)[:240]}"
            logger.error("[BROWSER] Falha ao instalar Chromium: %s", self.install_error)

    async def _probe_chromium(self) -> None:
        self.install_status = "checking"
        browser = None
        try:
            browser = await asyncio.wait_for(
                self._playwright.chromium.launch(
                    headless=True,
                    args=["--disable-dev-shm-usage", "--no-first-run", "--no-sandbox"],
                ),
                timeout=self.settings.browser_start_timeout,
            )
            page = await browser.new_page()
            await page.set_content("<title>CraftPlay browser probe</title>")
            self.launch_ready = True
            self.install_status = "ready"
            self.install_error = ""
            logger.info("[BROWSER] Chromium instalado, executado e pronto")
        except Exception as exc:
            self.launch_ready = False
            self.install_status = "failed"
            self.install_error = f"{type(exc).__name__}: Chromium nao executou neste host"
            logger.error("[BROWSER] Probe do Chromium falhou (%s)", type(exc).__name__)
        finally:
            if browser:
                await browser.close()

    async def _start_screencast(self, runtime: BrowserRuntime) -> None:
        runtime.cdp = await runtime.context.new_cdp_session(runtime.page)
        await runtime.cdp.send("Page.enable")
        runtime.cdp.on(
            "Page.screencastFrame",
            lambda frame: asyncio.create_task(self._handle_screencast_frame(runtime, frame)),
        )
        await runtime.cdp.send("Page.startScreencast", {
            "format": "jpeg",
            "quality": min(80, max(30, self.settings.browser_frame_quality)),
            "maxWidth": min(1280, self.viewport_width),
            "maxHeight": min(720, self.viewport_height),
            "everyNthFrame": 1,
        })

    async def capture_frame(self, room_id: str) -> dict:
        """Capture a guaranteed frame when CDP emitted before a viewer subscribed."""
        image = await self.capture_frame_bytes(room_id)
        return {
            "event": "BROWSER_FRAME",
            "mime": "image/jpeg",
            "data": base64.b64encode(image).decode("ascii"),
            "timestamp": int(time.time() * 1000),
        }

    async def capture_frame_bytes(self, room_id: str) -> bytes:
        """Return a JPEG screenshot for the authenticated HTTP fallback."""
        runtime = self._require(room_id)
        if runtime.last_frame_data:
            return runtime.last_frame_data
        return await runtime.page.screenshot(
            type="jpeg",
            quality=min(80, max(30, self.settings.browser_frame_quality)),
        )

    async def _handle_screencast_frame(self, runtime: BrowserRuntime, frame: dict) -> None:
        try:
            await runtime.cdp.send("Page.screencastFrameAck", {"sessionId": frame["sessionId"]})
            now = time.monotonic()
            fps = min(10, max(1, self.settings.browser_frame_fps))
            if now - runtime.last_frame_at < 1 / fps:
                return
            runtime.last_frame_at = now
            encoded = frame.get("data", "")
            if encoded:
                runtime.last_frame_data = base64.b64decode(encoded)
            from backend.room_manager import room_manager
            await room_manager.broadcast_browser_frame(runtime.room_id, {
                "event": "BROWSER_FRAME", "mime": "image/jpeg", "data": encoded,
                "timestamp": int(time.time() * 1000),
            })
        except Exception:
            logger.debug("Frame de screencast descartado", exc_info=True)

    async def navigate(self, room_id: str, url: str) -> str:
        runtime = self._require(room_id)
        safe = await validate_public_url(url, enforce_allowlist=runtime.shield.mode == "STRICT")
        await runtime.page.goto(safe.url, wait_until="domcontentloaded", timeout=self.settings.browser_start_timeout * 1000)
        # Revalidate the final hostname to mitigate redirects and DNS rebinding.
        final = await validate_public_url(runtime.page.url, enforce_allowlist=runtime.shield.mode == "STRICT")
        runtime.current_url = final.url
        runtime.last_activity = time.monotonic()
        return runtime.current_url

    async def action(self, room_id: str, event: str, payload: dict) -> str:
        runtime = self._require(room_id)
        page = runtime.page
        width, height = self.viewport_width, self.viewport_height
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
        return runtime.current_url

    async def close(self, room_id: str, *, preserve_profile: bool = False) -> None:
        runtime = self.sessions.pop(room_id, None)
        if not runtime:
            return
        try:
            await browser_publisher.close(room_id)
            if runtime.cdp:
                try:
                    await runtime.cdp.send("Page.stopScreencast")
                    await runtime.cdp.detach()
                except Exception:
                    pass
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
    def _memory_limit_mb() -> int | None:
        for candidate in (Path("/sys/fs/cgroup/memory.max"), Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")):
            try:
                value = candidate.read_text(encoding="utf-8").strip()
                if value and value != "max":
                    limit = int(value) // (1024 * 1024)
                    if 0 < limit < 1024 * 1024:
                        return limit
            except (OSError, ValueError):
                continue
        return None

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
