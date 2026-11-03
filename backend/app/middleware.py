"""Pure ASGI middleware: request context and access log, security headers, body size limit.

Pure ASGI (rather than ``BaseHTTPMiddleware``) keeps Server-Sent Events unbuffered.
Order, outermost first: request context -> security headers -> CORS -> body size limit -> app.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Sequence

from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import error_response
from app.logging_config import request_id_var
from app.security import IPNetwork, resolve_client_ip

access_logger = logging.getLogger("app.access")
logger = logging.getLogger(__name__)

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
DOCS_PATH = "/api/docs"
CORS_REJECTED_PREFIX = "Disallowed CORS "

SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
)
CSP_HEADER = ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")


def security_headers_for(path: str) -> list[tuple[str, str]]:
    """Security headers for a response to ``path`` (Swagger UI gets no CSP: it loads a CDN)."""
    headers = list(SECURITY_HEADERS)
    if path != DOCS_PATH:
        headers.append(CSP_HEADER)
    return headers


class RequestContextMiddleware:
    """Request id, client IP, access log and the last-resort ``500 internal_error`` envelope.

    Unhandled exceptions are converted here (inside the server's own error middleware) so that
    500 responses still carry ``X-Request-ID`` and the security headers.
    """

    def __init__(self, app: ASGIApp, trusted_proxies: Sequence[IPNetwork] = ()) -> None:
        self.app = app
        self.trusted_proxies = tuple(trusted_proxies)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        incoming = headers.get("x-request-id")
        request_id = (
            incoming if incoming and REQUEST_ID_PATTERN.match(incoming) else uuid.uuid4().hex
        )
        peer = scope.get("client")
        client_ip = resolve_client_ip(
            peer[0] if peer else None, headers.get("x-forwarded-for"), self.trusted_proxies
        )
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        state["client_ip"] = client_ip
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_holder = {"status": 500, "started": False}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                status_holder["started"] = True
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception("Unhandled error while handling %s %s", scope["method"], scope["path"])
            if not status_holder["started"]:
                response = error_response(
                    500,
                    "internal_error",
                    "An unexpected error occurred.",
                    {"request_id": request_id},
                    dict(security_headers_for(scope["path"])),
                )
                await response(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            access_logger.info(
                "%s %s %s %.1fms",
                scope["method"],
                scope["path"],
                status_holder["status"],
                duration_ms,
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status_holder["status"],
                    "duration_ms": duration_ms,
                    "client_ip": client_ip,
                },
            )
            request_id_var.reset(token)


class SecurityHeadersMiddleware:
    """Adds the security headers to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        extra = security_headers_for(scope["path"])

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in extra:
                    if name not in headers:
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_wrapper)


class EnvelopeCORSMiddleware(CORSMiddleware):
    """Starlette's CORS middleware, but rejected preflights use the JSON error envelope.

    Starlette answers them itself with a ``text/plain`` 400; the contract wants the envelope on
    every 4xx/5xx. The CORS headers Starlette computed are kept.
    """

    def preflight_response(self, request_headers: Headers) -> Response:
        response = super().preflight_response(request_headers)
        if response.status_code < 400:
            return response
        # Starlette's body is "Disallowed CORS origin, method, headers" (whichever failed).
        text = bytes(response.body).decode("utf-8", "replace")
        rejected = text.removeprefix(CORS_REJECTED_PREFIX).split(", ")
        details = {"rejected": rejected} if text.startswith(CORS_REJECTED_PREFIX) else None
        headers = {
            name: value
            for name, value in response.headers.items()
            if name.lower() not in {"content-length", "content-type"}
        }
        return error_response(
            response.status_code,
            "cors_rejected",
            "The cross-origin request is not allowed.",
            details,
            headers,
        )


class BodySizeLimitMiddleware:
    """Rejects bodies above the limit with ``413 payload_too_large``.

    ``Content-Length`` above the limit is rejected before reading. Otherwise the body is read
    (counting chunked uploads) and replayed to the application; the limit is ``import_max_bytes``
    for ``POST /api/import`` and ``max_bytes`` elsewhere.
    """

    def __init__(self, app: ASGIApp, max_bytes: int, import_max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.import_max_bytes = import_max_bytes

    def _limit_for(self, scope: Scope) -> int:
        if scope["method"] == "POST" and scope["path"] == "/api/import":
            return self.import_max_bytes
        return self.max_bytes

    async def _reject(self, scope: Scope, receive: Receive, send: Send, limit: int) -> None:
        response = error_response(
            413,
            "payload_too_large",
            "The request body is too large.",
            {"max_bytes": limit},
            {"Connection": "close"},
        )
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in {"GET", "HEAD", "OPTIONS"}:
            await self.app(scope, receive, send)
            return
        limit = self._limit_for(scope)
        declared = Headers(scope=scope).get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            await self._reject(scope, receive, send, limit)
            return

        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            size += len(body)
            if size > limit:
                await self._reject(scope, receive, send, limit)
                return
            chunks.append(body)
            if not message.get("more_body", False):
                break

        replayed = False
        full_body = b"".join(chunks)

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": full_body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
