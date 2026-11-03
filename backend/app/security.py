"""API-key authentication, client identity and rate limiting."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import math
import time
from collections.abc import Sequence

from limits import RateLimitItem
from limits.aio.strategies import MovingWindowRateLimiter
from limits.storage import storage_from_string

from app.errors import AppError

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


class ApiKeyVerifier:
    """Checks ``X-API-Key`` values in constant time.

    The candidate's SHA-256 digest is compared with the digest of every configured key using
    ``hmac.compare_digest`` without an early exit, so timing reveals neither which key matched
    nor the key lengths.
    """

    def __init__(self, keys: Sequence[str]) -> None:
        self._digests = [_digest(key) for key in keys]

    @property
    def enabled(self) -> bool:
        return bool(self._digests)

    def verify(self, candidate: str | None) -> bool:
        if candidate is None:
            return False
        candidate_digest = _digest(candidate)
        matched = False
        for digest in self._digests:
            matched |= hmac.compare_digest(candidate_digest, digest)
        return matched


def key_identity(key: str) -> str:
    """Rate-limit identity for an authenticated client (never the key itself)."""
    return "key:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _parse_ip(value: str) -> IPAddress | None:
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def resolve_client_ip(
    peer: str | None, forwarded_for: str | None, trusted: Sequence[IPNetwork]
) -> str:
    """Client address, honouring ``X-Forwarded-For`` only from trusted proxies.

    When the direct peer is trusted, ``X-Forwarded-For`` is walked right to left and the first
    address that is not a trusted proxy wins. An invalid entry stops the walk and the peer is used.
    """
    peer_ip = _parse_ip(peer) if peer else None
    if peer_ip is None:
        return peer or "unknown"
    if not trusted or not any(peer_ip in net for net in trusted) or not forwarded_for:
        return str(peer_ip)
    for raw in reversed(forwarded_for.split(",")):
        hop = _parse_ip(raw)
        if hop is None:
            return str(peer_ip)
        if not any(hop in net for net in trusted):
            return str(hop)
    return str(peer_ip)


def ip_bucket(client_ip: str) -> str:
    """Rate-limit bucket for an address: IPv4 as is, IPv6 by its /64 network."""
    address = _parse_ip(client_ip)
    if address is None:
        return client_ip
    if isinstance(address, ipaddress.IPv6Address):
        return str(ipaddress.IPv6Network((address, 64), strict=False))
    return str(address)


def ip_identity(client_ip: str) -> str:
    return "ip:" + ip_bucket(client_ip)


class RateLimiter:
    """Moving-window limits from the ``limits`` package (async API)."""

    def __init__(self, storage_uri: str, *, enabled: bool = True) -> None:
        uri = storage_uri if storage_uri.startswith("async+") else "async+" + storage_uri
        self.enabled = enabled
        self._storage = storage_from_string(uri)
        self._limiter = MovingWindowRateLimiter(self._storage)

    async def hit(self, items: Sequence[RateLimitItem], group: str, identity: str) -> None:
        """Count one request; raises a ``429 rate_limited`` :class:`AppError` when refused."""
        if not self.enabled:
            return
        for item in items:
            if not await self._limiter.hit(item, group, identity):
                raise await self._refusal(item, group, identity)

    async def check(self, items: Sequence[RateLimitItem], group: str, identity: str) -> None:
        """Raise ``429`` when another hit would be refused, without counting this request."""
        if not self.enabled:
            return
        for item in items:
            if not await self._limiter.test(item, group, identity):
                raise await self._refusal(item, group, identity)

    async def _refusal(self, item: RateLimitItem, group: str, identity: str) -> AppError:
        stats = await self._limiter.get_window_stats(item, group, identity)
        retry_after = max(1, math.ceil(stats.reset_time - time.time()))
        return AppError(
            429,
            "rate_limited",
            "Too many requests. Try again later.",
            {"retry_after": retry_after},
            {"Retry-After": str(retry_after)},
        )

    async def aclose(self) -> None:
        """Stop the in-memory storage's expiry task, if one is running."""
        timer = getattr(self._storage, "timer", None)
        if isinstance(timer, asyncio.Task) and not timer.done():
            timer.cancel()
            await asyncio.gather(timer, return_exceptions=True)
