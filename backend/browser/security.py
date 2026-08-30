import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import select

from backend.database import SessionLocal
from backend.models import AllowedDomain, BlockedDomain


BLOCKED_HOSTS = {"localhost", "localhost.localdomain", "metadata.google.internal"}
BLOCKED_METADATA_IPS = {"169.254.169.254", "100.100.100.200"}


@dataclass(slots=True)
class SafeURL:
    url: str
    hostname: str
    addresses: tuple[str, ...]


def _is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified or address in BLOCKED_METADATA_IPS
    )


async def validate_public_url(url: str, *, enforce_allowlist: bool = False) -> SafeURL:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Somente URLs HTTP e HTTPS sao permitidas")
    if parsed.username or parsed.password:
        raise ValueError("Credenciais na URL nao sao permitidas")
    hostname = (parsed.hostname or "").rstrip(".").casefold()
    if not hostname or hostname in BLOCKED_HOSTS:
        raise ValueError("Destino local ou invalido")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError("Porta invalida") from exc

    with SessionLocal() as db:
        blocked = next((row for row in db.scalars(select(BlockedDomain)).all()
                        if hostname == row.domain.lstrip("*.") or hostname.endswith(f".{row.domain.lstrip('*.')}")), None)
        if blocked:
            raise ValueError(f"Dominio bloqueado: {blocked.reason or hostname}")
        if enforce_allowlist:
            allowed = db.scalars(select(AllowedDomain)).all()
            if allowed and not any(hostname == row.domain or hostname.endswith(f".{row.domain}") for row in allowed):
                raise ValueError("Dominio fora da lista permitida")

    try:
        results = await asyncio.to_thread(socket.getaddrinfo, hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Nao foi possivel resolver o dominio") from exc
    addresses = tuple(sorted({item[4][0] for item in results}))
    if not addresses or any(not _is_public_address(address) for address in addresses):
        raise ValueError("O destino resolve para uma rede privada ou reservada")
    return SafeURL(url=parsed.geturl(), hostname=hostname, addresses=addresses)


def same_site(hostname: str, original: str) -> bool:
    return hostname == original or hostname.endswith(f".{original}") or original.endswith(f".{hostname}")


def is_allowed_hostname(hostname: str) -> bool:
    with SessionLocal() as db:
        return any(hostname == row.domain or hostname.endswith(f".{row.domain}") for row in db.scalars(select(AllowedDomain)).all())
