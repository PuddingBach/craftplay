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


def load_domain_policy() -> tuple[dict[str, str], tuple[str, ...]]:
    """Load dashboard domain rules once for a browser session."""
    with SessionLocal() as db:
        blocked = {
            row.domain.casefold(): row.reason
            for row in db.scalars(select(BlockedDomain)).all()
        }
        allowed = tuple(row.domain.casefold() for row in db.scalars(select(AllowedDomain)).all())
    return blocked, allowed


def _domain_matches(hostname: str, rule: str) -> bool:
    normalized = rule.lstrip("*.").rstrip(".").casefold()
    return bool(normalized) and (hostname == normalized or hostname.endswith(f".{normalized}"))


def _is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified or address in BLOCKED_METADATA_IPS
    )


async def validate_public_url(
    url: str,
    *,
    enforce_allowlist: bool = False,
    blocked_domains: dict[str, str] | None = None,
    allowed_domains: tuple[str, ...] | None = None,
) -> SafeURL:
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

    if blocked_domains is None or allowed_domains is None:
        loaded_blocked, loaded_allowed = load_domain_policy()
        blocked_domains = loaded_blocked if blocked_domains is None else blocked_domains
        allowed_domains = loaded_allowed if allowed_domains is None else allowed_domains
    blocked = next(((rule, reason) for rule, reason in blocked_domains.items() if _domain_matches(hostname, rule)), None)
    if blocked:
        raise ValueError(f"Dominio bloqueado: {blocked[1] or hostname}")
    if enforce_allowlist and allowed_domains and not any(_domain_matches(hostname, rule) for rule in allowed_domains):
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
    _, allowed = load_domain_policy()
    return any(_domain_matches(hostname, rule) for rule in allowed)
