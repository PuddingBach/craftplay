import asyncio
from collections import Counter
from urllib.parse import urlparse

from backend.browser.security import _domain_matches, load_domain_policy, same_site, validate_public_url


TRACKER_MARKERS = (
    "doubleclick.net", "googlesyndication.com", "google-analytics.com", "adservice.google.",
    "facebook.net/tr", "connect.facebook.net", "scorecardresearch.com", "taboola.com",
    "outbrain.com", "hotjar.com", "/ads/", "/advert", "analytics.", "tracker.",
)


class BrowserShield:
    def __init__(self, mode: str, original_host: str, allow_downloads: bool = False):
        self.mode = mode.upper()
        self.original_host = original_host
        self.allow_downloads = allow_downloads
        self.metrics = Counter(ads=0, trackers=0, popups=0, redirects=0, downloads=0)
        self.events: list[dict] = []
        self.blocked_domains: dict[str, str] = {}
        self.allowed_domains: tuple[str, ...] = ()
        self.validated_hosts: set[str] = set()
        self.host_locks: dict[str, asyncio.Lock] = {}

    def record(self, kind: str, url: str = "") -> None:
        self.metrics[kind] += 1
        self.events.append({"kind": kind, "host": urlparse(url).hostname or ""})
        self.events = self.events[-100:]

    async def install(self, context, page) -> None:
        self.blocked_domains, self.allowed_domains = load_domain_policy()
        await context.route("**/*", self._route)
        context.on("page", lambda popup: self._schedule_popup_close(popup))
        page.on("download", lambda download: self._schedule_download_cancel(download))

    async def _route(self, route) -> None:
        request = route.request
        target = request.url
        host = (urlparse(target).hostname or "").casefold()
        lowered = target.casefold()
        if self.mode != "OFF" and any(marker in lowered for marker in TRACKER_MARKERS):
            kind = "trackers" if "analytic" in lowered or "tracker" in lowered else "ads"
            self.record(kind, target)
            await route.abort("blockedbyclient")
            return
        if target.startswith(("http://", "https://")):
            try:
                lock = self.host_locks.setdefault(host, asyncio.Lock())
                async with lock:
                    if host not in self.validated_hosts:
                        await validate_public_url(
                            target,
                            blocked_domains=self.blocked_domains,
                            allowed_domains=self.allowed_domains,
                        )
                        self.validated_hosts.add(host)
            except ValueError:
                self.record("redirects", target)
                await route.abort("blockedbyclient")
                return
        allowed = any(_domain_matches(host, rule) for rule in self.allowed_domains)
        if self.mode == "STRICT" and request.resource_type == "document" and not same_site(host, self.original_host) and not allowed:
            self.record("redirects", target)
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    def _schedule_popup_close(self, popup) -> None:
        import asyncio
        self.record("popups", popup.url)
        if self.mode in {"STANDARD", "STRICT"}:
            asyncio.create_task(popup.close())

    def _schedule_download_cancel(self, download) -> None:
        import asyncio
        if not self.allow_downloads or self.mode == "STRICT":
            self.record("downloads", download.url)
            asyncio.create_task(download.cancel())

    def status(self) -> dict:
        return {"mode": self.mode, **dict(self.metrics), "recent_events": list(self.events)}
