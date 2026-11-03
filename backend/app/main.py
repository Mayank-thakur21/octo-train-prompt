"""Application factory.

Run with ``uvicorn app.main:create_app --factory`` (or ``uvicorn app.main:app``, which builds
the app from the environment on first access).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware import Middleware

from app import APP_NAME, __version__
from app.config import Settings, get_settings
from app.db import Database
from app.errors import install_exception_handlers
from app.logging_config import configure_logging
from app.middleware import (
    BodySizeLimitMiddleware,
    EnvelopeCORSMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.providers.registry import REAL_PROVIDERS, ProviderRegistry, build_registry
from app.routers import (
    compare,
    data,
    evals,
    health,
    history,
    models,
    prompts,
    runs,
    suites,
    templates,
)
from app.security import ApiKeyVerifier, RateLimiter
from app.services.evaluation import recover_interrupted, shutdown_evals
from app.state import AppState

logger = logging.getLogger("app")

OPEN_API_WARNING = (
    "API_KEYS is empty: the API is open to anyone who can reach it while provider keys are "
    "configured."
)

CORS_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
CORS_HEADERS = ["Content-Type", "X-API-Key", "X-Request-ID"]
CORS_EXPOSE = ["X-Request-ID", "Retry-After", "Content-Disposition"]


def _log_startup(state: AppState) -> None:
    settings, registry = state.settings, state.registry
    configured = [name.value for name in REAL_PROVIDERS if registry.is_configured(name)]
    logger.info(
        "%s %s starting: providers=%s catalog=%d default_model=%s auth=%s rate_limiting=%s",
        APP_NAME,
        __version__,
        ",".join(configured) or "none (demo mode)",
        len(registry.models()),
        registry.effective_default_model().id,
        "yes" if settings.auth_required else "no",
        "on" if settings.rate_limit_enabled else "off",
    )
    if not settings.auth_required and configured:
        logger.warning(OPEN_API_WARNING)


def create_app(
    settings: Settings | None = None, registry: ProviderRegistry | None = None
) -> FastAPI:
    """Build the FastAPI application.

    ``registry`` lets tests inject providers; otherwise real providers are built from settings.
    Invalid configuration raises ``ValueError`` (or a validation error) here, at startup.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format, settings.secret_values())
    registry = registry or build_registry(settings)
    state = AppState(
        settings=settings,
        registry=registry,
        db=Database(settings.database_url),
        limiter=RateLimiter(settings.rate_limit_storage_uri, enabled=settings.rate_limit_enabled),
        verifier=ApiKeyVerifier(settings.api_key_values),
        provider_semaphore=asyncio.Semaphore(settings.provider_concurrency),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await state.db.init()
        recovered = await recover_interrupted(state)
        if recovered:
            logger.warning("Marked %d interrupted evaluation(s) as failed", recovered)
        _log_startup(state)
        try:
            yield
        finally:
            await shutdown_evals(state)
            await state.registry.aclose()
            await state.limiter.aclose()
            await state.db.dispose()
            logger.info("%s stopped", APP_NAME)

    middleware = [
        Middleware(RequestContextMiddleware, trusted_proxies=settings.trusted_proxy_networks),
        Middleware(SecurityHeadersMiddleware),
        Middleware(
            EnvelopeCORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=CORS_METHODS,
            allow_headers=CORS_HEADERS,
            expose_headers=CORS_EXPOSE,
            allow_credentials=False,
        ),
        Middleware(
            BodySizeLimitMiddleware,
            max_bytes=settings.max_body_bytes,
            import_max_bytes=settings.import_max_bytes,
        ),
    ]
    app = FastAPI(
        title=f"{APP_NAME} API",
        version=__version__,
        description="Run, compare, version and evaluate prompts across model providers.",
        docs_url="/api/docs" if settings.docs_enabled else None,
        openapi_url="/api/openapi.json" if settings.docs_enabled else None,
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
        lifespan=lifespan,
        middleware=middleware,
    )
    app.state.studio = state
    app.state.eval_tasks = state.eval_tasks
    install_exception_handlers(app)
    for module in (health, models, runs, templates, prompts, compare, suites, evals, history, data):
        app.include_router(module.router)
    return app


_app: FastAPI | None = None


def __getattr__(name: str) -> Any:
    """``app.main:app`` builds the application lazily from the environment (PEP 562)."""
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
