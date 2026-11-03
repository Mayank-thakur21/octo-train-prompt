"""FastAPI dependencies: app state, settings, registry, authentication and rate limiting."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Request, Response
from fastapi.routing import APIRoute

from app.config import Settings
from app.errors import AppError
from app.providers.registry import ProviderRegistry
from app.security import ip_identity, key_identity
from app.state import AppState

API_KEY_HEADER = "x-api-key"
# Request-scope key under which the guard keeps the rate-limit identity it authenticated.
_IDENTITY_STATE_KEY = "rate_limit_identity"


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.studio
    return state


def get_settings_dep(request: Request) -> Settings:
    return get_state(request).settings


def get_registry(request: Request) -> ProviderRegistry:
    return get_state(request).registry


StateDep = Annotated[AppState, Depends(get_state)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_registry)]


def client_ip(request: Request) -> str:
    """Client address computed by the request middleware (proxy aware)."""
    ip = request.scope.get("state", {}).get("client_ip")
    if isinstance(ip, str):
        return ip
    return request.client.host if request.client else "unknown"


def _unauthorized() -> AppError:
    return AppError(
        401,
        "unauthorized",
        "A valid API key is required.",
        headers={"WWW-Authenticate": 'ApiKey header="X-API-Key"'},
    )


class Guard:
    """Authentication (optional) followed by the rate limit of a group.

    With ``API_KEYS`` set, a missing or wrong ``X-API-Key`` is a ``401``. Wrong keys count
    against ``RATE_LIMIT_AUTH_FAILURES`` per client IP; once that budget is spent, further
    attempts from the IP get ``429`` before any key comparison.
    """

    def __init__(self, group: str | None, *, auth: bool = True) -> None:
        self.group = group
        self.auth = auth

    async def authenticate(self, request: Request) -> str:
        """Check the API key (when required) and return the rate-limit identity.

        The result is kept on the request, so the route-level early check
        (:class:`AuthFirstRoute`) and the dependency itself authenticate only once.
        """
        request_state = request.scope.setdefault("state", {})
        cached = request_state.get(_IDENTITY_STATE_KEY)
        if isinstance(cached, str):
            return cached
        state = get_state(request)
        identity = ip_identity(client_ip(request))
        presented = request.headers.get(API_KEY_HEADER)
        if state.verifier.enabled:
            if self.auth:
                if presented is None:
                    raise _unauthorized()
                failures = state.settings.rate_limits("auth_failures")
                await state.limiter.check(failures, "auth_failures", identity)
                if not state.verifier.verify(presented):
                    await state.limiter.hit(failures, "auth_failures", identity)
                    raise _unauthorized()
                identity = key_identity(presented)
            elif presented is not None and state.verifier.verify(presented):
                identity = key_identity(presented)
        request_state[_IDENTITY_STATE_KEY] = identity
        return identity

    async def __call__(self, request: Request) -> None:
        identity = await self.authenticate(request)
        if self.group is not None:
            state = get_state(request)
            await state.limiter.hit(state.settings.rate_limits(self.group), self.group, identity)


class AuthFirstRoute(APIRoute):
    """An ``APIRoute`` that checks the API key before FastAPI reads the request body.

    FastAPI decodes a JSON body before it solves dependencies, so without this a request with
    no key (or a wrong one) and a malformed body would get ``422`` instead of ``401``, and a
    wrong key would not count against ``RATE_LIMIT_AUTH_FAILURES``. The group rate limit still
    runs as the route dependency, after the body is valid.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()
        route_guard = next(
            (dep.dependency for dep in self.dependencies if isinstance(dep.dependency, Guard)),
            None,
        )
        if route_guard is None:
            return handler

        async def authenticate_then_handle(request: Request) -> Response:
            await route_guard.authenticate(request)
            return await handler(request)

        return authenticate_then_handle


def guard(group: str | None, *, auth: bool = True) -> Any:
    """``Depends`` marker for a route's auth + rate-limit group."""
    return Depends(Guard(group, auth=auth))
