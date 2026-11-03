"""Shared fixtures: settings, app and client factories, and a guard against real network use."""

from __future__ import annotations

import socket
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.main import create_app
from app.providers.base import Provider, ProviderName
from app.providers.registry import build_registry

PROVIDER_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_PROFILE",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENAI_USE_VERTEXAI",
    "API_KEYS",
)

TEST_API_KEY = "test-api-key-0123456789"
OTHER_API_KEY = "other-api-key-9876543210"


class NetworkBlockedError(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly on any attempt to open a real network connection."""

    def blocked(*_args: Any, **_kwargs: Any) -> Any:
        raise NetworkBlockedError("network access is disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    for name in PROVIDER_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


SettingsFactory = Callable[..., Settings]


@pytest.fixture
def make_settings(tmp_path: Path) -> SettingsFactory:
    """Settings with a temporary SQLite file, instant demo streaming and generous limits."""

    def factory(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "database_url": f"sqlite+aiosqlite:///{tmp_path / 'studio.db'}",
            "demo_stream_delay_ms": 0,
            "provider_max_retries": 0,
            "rate_limit_default": "10000/minute",
            "rate_limit_runs": "10000/minute",
            "rate_limit_compare": "10000/minute",
            "rate_limit_evals": "10000/minute",
            "rate_limit_tokens": "10000/minute",
            "rate_limit_data": "10000/minute",
            "rate_limit_auth_failures": "10000/minute",
            "log_level": "WARNING",
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    return factory


@pytest.fixture
def settings(make_settings: SettingsFactory) -> Settings:
    return make_settings()


ClientFactory = Callable[..., AbstractAsyncContextManager[httpx2.AsyncClient]]


@asynccontextmanager
async def running_client(app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    """An HTTP client bound to the app, inside the app's lifespan."""
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.fixture
def make_app(make_settings: SettingsFactory) -> Callable[..., FastAPI]:
    def factory(
        providers: Mapping[ProviderName, Provider] | None = None,
        settings: Settings | None = None,
        **overrides: Any,
    ) -> FastAPI:
        resolved = settings or make_settings(**overrides)
        return create_app(resolved, build_registry(resolved, providers))

    return factory


@pytest.fixture
def make_client(make_app: Callable[..., FastAPI]) -> ClientFactory:
    """``async with make_client(providers=..., **settings) as client`` for a fresh app."""

    def factory(
        providers: Mapping[ProviderName, Provider] | None = None,
        settings: Settings | None = None,
        **overrides: Any,
    ) -> AbstractAsyncContextManager[httpx2.AsyncClient]:
        return running_client(make_app(providers, settings, **overrides))

    return factory


@pytest.fixture
async def client(make_client: ClientFactory) -> AsyncIterator[httpx2.AsyncClient]:
    """Client for an app with only the offline demo provider available."""
    async with make_client() as http:
        yield http
