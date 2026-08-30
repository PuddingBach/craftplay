import asyncio
import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx


ALLOWED_TYPES = {"hls", "dash", "mp4", "embed", "youtube", "vimeo"}
VIDEO_CONTENT_TYPES = ("video/", "application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/mpegurl")


def is_public_https_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return False
        host = parsed.hostname.casefold()
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False


async def _resolved_hosts_are_public(hostname: str) -> bool:
    try:
        addresses = await asyncio.get_running_loop().run_in_executor(
            None, lambda: socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        )
        return bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_global for item in addresses)
    except (OSError, ValueError):
        return False


def embed_is_allowed(headers: httpx.Headers) -> bool:
    xframe = headers.get("x-frame-options", "").casefold()
    csp = headers.get("content-security-policy", "").casefold()
    return not (
        "deny" in xframe or "sameorigin" in xframe
        or bool(re.search(r"frame-ancestors\s+(?:'none'|'self')(?:\s|;|$)", csp))
    )


async def validate_media_url(url: str, source_type: str, timeout: float = 10) -> tuple[bool, str]:
    source_type = source_type.casefold()
    if source_type not in ALLOWED_TYPES or not is_public_https_url(url):
        return False, "URL HTTPS publica invalida"
    host = urlparse(url).hostname or ""
    if not await _resolved_hosts_are_public(host):
        return False, "Destino nao publico ou indisponivel"
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("GET", url, headers={"Range": "bytes=0-4095", "User-Agent": "CraftPlay/1.0"}) as response:
                status = response.status_code
                headers = response.headers
                final_url = str(response.url)
                body = b""
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) >= 4096:
                        break
        final_host = urlparse(final_url).hostname or ""
        if not is_public_https_url(final_url) or not await _resolved_hosts_are_public(final_host):
            return False, "Redirecionamento para destino nao publico"
        if status not in {200, 206}:
            return False, f"HTTP {status}"
        content_type = headers.get("content-type", "").split(";", 1)[0].casefold()
        body = body[:4096].lower()
        if source_type == "hls" and not (b"#extm3u" in body or "mpegurl" in content_type):
            return False, "Manifesto HLS invalido"
        if source_type == "dash" and not (b"<mpd" in body or "dash+xml" in content_type):
            return False, "Manifesto DASH invalido"
        if source_type == "mp4" and not (content_type.startswith(VIDEO_CONTENT_TYPES) or b"ftyp" in body):
            return False, f"Conteudo nao e video ({content_type or 'sem MIME'})"
        if source_type in {"embed", "youtube", "vimeo"} and not embed_is_allowed(headers):
            return False, "Incorporacao bloqueada pelo servidor"
        return True, f"HTTP {status} {content_type or 'ok'}"
    except httpx.HTTPError as exc:
        return False, f"{type(exc).__name__}: {exc}"


def normalized_title(value: str) -> str:
    import unicodedata

    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))
