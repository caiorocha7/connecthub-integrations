"""Outbound URL validation to mitigate SSRF.

Blocks private, loopback, link-local, multicast, reserved and cloud-metadata addresses.
Hosts listed in ``SSRF_ALLOWED_HOSTS`` (e.g. the local simulator) are allowed in development,
but cloud metadata endpoints are *always* blocked. Redirects are never followed by the worker.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from app.core.config import get_settings

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

ALLOWED_SCHEMES = {"http", "https"}
METADATA_HOSTS = {
    "metadata.google.internal",
    "metadata",
    "metadata.azure.com",
    "instance-data",
    "instance-data.ec2.internal",
}
METADATA_IPS: set[IPAddress] = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("169.254.170.2"),
    ipaddress.ip_address("100.100.100.200"),
    ipaddress.ip_address("fd00:ec2::254"),
}
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


class UnsafeURLError(ValueError):
    pass


def _ip_is_public(ip: IPAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return _ip_is_public(ip.ipv4_mapped)
    if isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve(host: str, port: int) -> list[IPAddress]:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"não foi possível resolver o host '{host}'") from exc
    return [ipaddress.ip_address(str(info[4][0]).split("%")[0]) for info in infos]


def validate_url_syntax(url: str) -> tuple[str, int]:
    parts = urlsplit(url)
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURLError("apenas URLs http ou https são permitidas")
    if not parts.hostname:
        raise UnsafeURLError("URL sem host")
    if parts.username or parts.password:
        raise UnsafeURLError("credenciais embutidas na URL não são permitidas")
    try:
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise UnsafeURLError("porta inválida") from exc
    return parts.hostname.lower().rstrip("."), port


def assert_safe_url(url: str, *, resolve: bool = True) -> None:
    """Raise :class:`UnsafeURLError` if the URL targets a forbidden destination."""
    host, port = validate_url_syntax(url)
    if host in METADATA_HOSTS:
        raise UnsafeURLError("acesso a serviços de metadados de infraestrutura é bloqueado")

    literal: IPAddress | None
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None and literal in METADATA_IPS:
        raise UnsafeURLError("acesso a serviços de metadados de infraestrutura é bloqueado")

    allowed = host in get_settings().ssrf_allowed_host_set
    if not resolve:
        if literal is not None and not allowed and not _ip_is_public(literal):
            raise UnsafeURLError("endereços internos ou privados não são permitidos")
        return

    addresses = [literal] if literal is not None else _resolve(host, port)
    for ip in addresses:
        if ip in METADATA_IPS:
            raise UnsafeURLError("acesso a serviços de metadados de infraestrutura é bloqueado")
        if not allowed and not _ip_is_public(ip):
            raise UnsafeURLError("endereços internos ou privados não são permitidos")
