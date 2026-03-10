"""
Network Safety — SSRF protection and URL validation.

Validates URLs before any HTTP request to prevent Server-Side Request Forgery.
Blocks private networks, localhost, cloud metadata endpoints, and non-HTTP schemes.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Blocked ranges
# ---------------------------------------------------------------------------

_BLOCKED_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    # Loopback
    ipaddress.IPv4Network("127.0.0.0/8"),
    ipaddress.IPv6Network("::1/128"),
    # Private ranges
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    # Link-local
    ipaddress.IPv4Network("169.254.0.0/16"),
    ipaddress.IPv6Network("fe80::/10"),
    # Carrier-grade NAT
    ipaddress.IPv4Network("100.64.0.0/10"),
    # Benchmarking
    ipaddress.IPv4Network("198.18.0.0/15"),
    # Documentation ranges (occasionally abused)
    ipaddress.IPv4Network("192.0.2.0/24"),
    ipaddress.IPv4Network("198.51.100.0/24"),
    ipaddress.IPv4Network("203.0.113.0/24"),
]

_BLOCKED_HOSTNAMES: set[str] = {
    "localhost",
    "metadata.google.internal",
    "metadata.internal",
    "instance-data",
}

# Cloud metadata endpoints (IP-based)
_BLOCKED_IPS: set[str] = {
    "169.254.169.254",  # AWS / GCP / Azure metadata
    "169.254.170.2",    # AWS ECS task metadata
    "fd00:ec2::254",    # AWS IPv6 metadata
}

_ALLOWED_SCHEMES: set[str] = {"http", "https"}


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class URLValidationResult:
    """Result of URL validation."""
    allowed: bool
    url: str
    reason: str = ""
    resolved_ip: str | None = None


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is in a blocked range."""
    # Let ValueError bubble up if ip_str is a hostname, not an IP.
    addr = ipaddress.ip_address(ip_str)

    if ip_str in _BLOCKED_IPS:
        return True

    for network in _BLOCKED_NETWORKS:
        if addr in network:
            return True

    return False


def validate_url(url: str) -> URLValidationResult:
    """
    Validate a URL against SSRF blocklists.

    Checks scheme, hostname, and static IP patterns. Does NOT resolve DNS
    (use validate_url_with_dns for that).
    """
    if not url or not isinstance(url, str):
        return URLValidationResult(
            allowed=False, url=str(url), reason="empty_or_invalid_url"
        )

    try:
        parsed = urlparse(url)
    except Exception:
        return URLValidationResult(
            allowed=False, url=url, reason="malformed_url"
        )

    # Check scheme
    if parsed.scheme not in _ALLOWED_SCHEMES:
        return URLValidationResult(
            allowed=False,
            url=url,
            reason=f"blocked_scheme:{parsed.scheme}",
        )

    # Check hostname
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return URLValidationResult(
            allowed=False, url=url, reason="missing_hostname"
        )

    # Blocked hostnames
    if hostname in _BLOCKED_HOSTNAMES:
        return URLValidationResult(
            allowed=False, url=url, reason=f"blocked_hostname:{hostname}"
        )

    # Check if hostname is a raw IP address
    try:
        if _is_private_ip(hostname):
            return URLValidationResult(
                allowed=False,
                url=url,
                reason=f"blocked_private_ip:{hostname}",
            )
    except ValueError:
        pass  # Not a raw IP — that's fine, it's a hostname

    # Block URLs with suspicious port access to common internal services
    port = parsed.port
    if port and port in {6379, 5432, 3306, 27017, 11211, 9200, 2379}:
        return URLValidationResult(
            allowed=False,
            url=url,
            reason=f"blocked_internal_port:{port}",
        )

    return URLValidationResult(allowed=True, url=url)


async def validate_url_with_dns(url: str) -> URLValidationResult:
    """
    Validate URL with DNS resolution to prevent DNS rebinding.

    Resolves the hostname and checks the resolved IP against blocked ranges.
    Uses run_in_executor to avoid blocking the event loop.
    """
    # First do the static check
    static_result = validate_url(url)
    if not static_result.allowed:
        return static_result

    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    # Resolve DNS in executor (getaddrinfo is blocking)
    loop = asyncio.get_event_loop()
    try:
        infos = await loop.run_in_executor(
            None,
            lambda: socket.getaddrinfo(hostname, parsed.port or 80, proto=socket.IPPROTO_TCP),
        )
    except socket.gaierror:
        return URLValidationResult(
            allowed=False,
            url=url,
            reason=f"dns_resolution_failed:{hostname}",
        )

    # Check all resolved IPs
    for family, _type, _proto, _canonname, sockaddr in infos:
        ip_str = sockaddr[0]
        if _is_private_ip(ip_str):
            return URLValidationResult(
                allowed=False,
                url=url,
                reason=f"dns_rebinding_blocked:{hostname}->{ip_str}",
                resolved_ip=ip_str,
            )

    # Get first resolved IP for logging
    resolved_ip = infos[0][4][0] if infos else None

    return URLValidationResult(
        allowed=True,
        url=url,
        resolved_ip=resolved_ip,
    )
