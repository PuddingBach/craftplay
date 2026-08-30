import time
from collections import defaultdict

from backend.playback.base import PlaybackProvider


class ProviderRegistry:
    def __init__(self, providers: list[PlaybackProvider] | None = None):
        self._providers: dict[str, PlaybackProvider] = {}
        self._metrics = defaultdict(lambda: {"provider_requests": 0, "provider_success": 0,
                                             "provider_failures": 0, "provider_restricted": 0,
                                             "provider_not_found": 0, "total_resolution_time": 0.0})
        for provider in providers or []:
            self.register(provider)

    def register(self, provider: PlaybackProvider) -> None:
        self._providers[provider.name] = provider

    def unregister(self, name: str) -> None:
        self._providers.pop(name, None)

    def enable(self, name: str) -> None:
        self._providers[name].enabled = True

    def disable(self, name: str) -> None:
        self._providers[name].enabled = False

    def get_providers(self, include_disabled: bool = False) -> list[PlaybackProvider]:
        values = self._providers.values()
        return sorted((p for p in values if include_disabled or p.enabled), key=lambda p: p.priority, reverse=True)

    async def get_healthy_providers(self) -> list[PlaybackProvider]:
        healthy = []
        for provider in self.get_providers():
            if (await provider.healthcheck()).get("healthy"):
                healthy.append(provider)
        return healthy

    def record(self, name: str, outcome: str, elapsed: float) -> None:
        metrics = self._metrics[name]
        metrics["provider_requests"] += 1
        metrics["total_resolution_time"] += elapsed
        key = {"success": "provider_success", "restricted": "provider_restricted", "not_found": "provider_not_found"}.get(outcome, "provider_failures")
        metrics[key] += 1

    def metrics(self, name: str) -> dict:
        values = dict(self._metrics[name]); count = values.pop("provider_requests")
        total = values.pop("total_resolution_time")
        return {"provider_requests": count, **values, "average_resolution_time": round(total / count, 3) if count else 0}

    @staticmethod
    def timer() -> float:
        return time.perf_counter()
