"""Health, readiness and server metadata."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.db import utcnow
from app.deps import AuthFirstRoute, StateDep, guard
from app.errors import AppError
from app.providers.base import PROVIDER_DISPLAY_NAMES, ProviderName
from app.schemas import HealthResponse, Limits, Meta, ProviderInfo, ReadyResponse

router = APIRouter(prefix="/api", route_class=AuthFirstRoute, tags=["meta"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness: the process is up."""
    return HealthResponse(version=__version__, time=utcnow())


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={503: {"description": "The database is not reachable."}},
)
async def ready(state: StateDep) -> ReadyResponse:
    """Readiness: the database answers a trivial query."""
    if not await state.db.ping():
        raise AppError(
            503, "not_ready", "The service is not ready.", {"checks": {"database": "error"}}
        )
    return ReadyResponse(checks={"database": "ok"})


@router.get("/meta", response_model=Meta, dependencies=[guard("default", auth=False)])
async def meta(state: StateDep) -> Meta:
    """Server name, version, auth requirement, configured providers and limits."""
    registry = state.registry
    names = [ProviderName.ANTHROPIC, ProviderName.OPENAI, ProviderName.GEMINI]
    if state.settings.demo_enabled:
        names.append(ProviderName.DEMO)
    return Meta(
        version=__version__,
        auth_required=state.settings.auth_required,
        demo_mode=registry.demo_mode(),
        default_model=registry.effective_default_model().id,
        providers=[
            ProviderInfo(
                id=name.value,
                display_name=PROVIDER_DISPLAY_NAMES[name],
                configured=registry.is_configured(name),
            )
            for name in names
        ],
        limits=Limits(**state.settings.limits_payload()),
    )
