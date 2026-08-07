import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_HOST_SUFFIXES = (
    ".localhost",
    ".localdomain",
    ".local",
    ".internal",
    ".lan",
    ".home",
    ".corp",
    ".svc",
    ".cluster.local",
)


def validate_webhook_url(webhook_url: str) -> None:
    parsed = urlparse(webhook_url)
    if parsed.scheme != "https":
        raise ValueError("webhook_url must use https://")
    if not parsed.hostname:
        raise ValueError("webhook_url must include a hostname")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(_BLOCKED_HOST_SUFFIXES):
        raise ValueError("webhook_url must resolve to a public internet address")

    try:
        addresses = _resolve_host_addresses(hostname, parsed.port)
    except OSError as exc:
        raise ValueError("webhook_url hostname could not be resolved") from exc
    if not addresses:
        raise ValueError("webhook_url hostname could not be resolved")

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if _is_blocked_address(ip):
            raise ValueError("webhook_url must resolve to a public internet address")


def _resolve_host_addresses(hostname: str, port: int | None) -> set[str]:
    try:
        return {hostname} if ipaddress.ip_address(hostname) else set()
    except ValueError:
        pass
    return {
        str(item[4][0])
        for item in socket.getaddrinfo(hostname, port or 443, type=socket.SOCK_STREAM)
    }


def _is_blocked_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_unspecified,
            ip.is_reserved,
        )
    )
