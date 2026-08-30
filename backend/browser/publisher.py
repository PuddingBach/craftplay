import asyncio
import shutil
from dataclasses import dataclass

from backend.config import get_settings

try:
    from livekit import api as livekit_api
except ImportError:
    livekit_api = None


@dataclass
class PublisherRuntime:
    ingress_id: str
    process: asyncio.subprocess.Process


class BrowserPublisher:
    def __init__(self):
        self.settings = get_settings()
        self.runtimes: dict[str, PublisherRuntime] = {}

    def status(self) -> str:
        ready = bool(
            livekit_api and shutil.which("gst-launch-1.0")
            and self.settings.livekit_url and self.settings.livekit_api_key and self.settings.livekit_api_secret
        )
        return "healthy" if ready else "unavailable"

    async def start(self, room_id: str, room_name: str, display: str) -> PublisherRuntime | None:
        if self.status() != "healthy" or room_id in self.runtimes:
            return self.runtimes.get(room_id)
        async with livekit_api.LiveKitAPI(
            self.settings.livekit_url.replace("wss://", "https://").replace("ws://", "http://"),
            self.settings.livekit_api_key,
            self.settings.livekit_api_secret,
        ) as client:
            info = await client.ingress.create_ingress(livekit_api.CreateIngressRequest(
                input_type=livekit_api.IngressInput.RTMP_INPUT,
                name=f"CraftPlay {room_id}", room_name=room_name,
                participant_identity=f"browser-{room_id}", participant_name="CraftPlay Browser",
                enable_transcoding=True,
            ))
        destination = f"{info.url.rstrip('/')}/{info.stream_key}"
        command = [
            "gst-launch-1.0", "-e",
            "ximagesrc", f"display-name={display}", "use-damage=0", "show-pointer=true", "!",
            f"video/x-raw,framerate={self.settings.browser_fps}/1", "!", "videoconvert", "!", "videoscale", "!",
            f"video/x-raw,width={self.settings.browser_width},height={self.settings.browser_height}", "!",
            "x264enc", "tune=zerolatency", "speed-preset=ultrafast", "bitrate=4000", f"key-int-max={self.settings.browser_fps * 2}", "!",
            "h264parse", "!", "queue", "!", "flvmux", "name=mux", "streamable=true",
            "pulsesrc", "device=@DEFAULT_MONITOR@", "!", "audioconvert", "!", "audioresample", "!",
            "voaacenc", "bitrate=128000", "!", "queue", "!", "mux.", "mux.", "!", "rtmp2sink", f"location={destination}",
        ]
        process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        runtime = PublisherRuntime(info.ingress_id, process)
        self.runtimes[room_id] = runtime
        return runtime

    async def close(self, room_id: str) -> None:
        runtime = self.runtimes.pop(room_id, None)
        if not runtime:
            return
        if runtime.process.returncode is None:
            runtime.process.terminate()
            try: await asyncio.wait_for(runtime.process.wait(), 5)
            except asyncio.TimeoutError: runtime.process.kill()
        if livekit_api and self.settings.livekit_url:
            try:
                async with livekit_api.LiveKitAPI(
                    self.settings.livekit_url.replace("wss://", "https://").replace("ws://", "http://"),
                    self.settings.livekit_api_key, self.settings.livekit_api_secret,
                ) as client:
                    await client.ingress.delete_ingress(livekit_api.DeleteIngressRequest(ingress_id=runtime.ingress_id))
            except Exception:
                pass


browser_publisher = BrowserPublisher()
