"""Shared run logic: model resolution, parameter resolution and guarded provider calls."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from app.config import Settings
from app.errors import (
    invalid_parameter,
    provider_not_configured,
    unknown_model,
)
from app.providers.base import (
    GenerationRequest,
    GenerationResult,
    ModelSpec,
    ProviderError,
    ProviderErrorKind,
    log_provider_failure,
)
from app.providers.catalog import default_max_tokens_for, effective_max_output_tokens
from app.state import AppState

logger = logging.getLogger(__name__)


def resolve_model_id(
    state: AppState, model_id: str | None, *, require_available: bool = True
) -> ModelSpec:
    """Catalog entry for ``model_id`` (null -> effective default).

    Raises ``unknown_model`` for ids outside the catalog and ``provider_not_configured`` when
    ``require_available`` and the provider has no key.
    """
    registry = state.registry
    spec = registry.effective_default_model() if model_id is None else registry.get_model(model_id)
    if spec is None:
        raise unknown_model(str(model_id))
    if require_available and not registry.is_available(spec):
        raise provider_not_configured(spec.provider.value, spec.id)
    return spec


def resolve_models(state: AppState, model_ids: Sequence[str]) -> list[ModelSpec]:
    return [resolve_model_id(state, model_id) for model_id in model_ids]


@dataclass(frozen=True)
class EffectiveParams:
    """Parameters actually sent for one model, with warnings for dropped ones."""

    temperature: float | None
    max_tokens: int
    thinking: bool
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, float | int | bool | None]:
        return {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "thinking": self.thinking,
        }


def effective_params(
    spec: ModelSpec, *, temperature: float | None, max_tokens: int, thinking: bool
) -> EffectiveParams:
    """Drop parameters the model does not support, with a warning for each."""
    warnings: list[str] = []
    if temperature is not None and not spec.supports_temperature:
        warnings.append(f"temperature is not supported by {spec.display_name} and was ignored.")
        temperature = None
    if thinking and not spec.supports_thinking:
        warnings.append(f"thinking is not supported by {spec.display_name} and was ignored.")
        thinking = False
    return EffectiveParams(temperature, max_tokens, thinking, tuple(warnings))


def resolve_max_tokens(
    specs: Sequence[ModelSpec], settings: Settings, requested: int | None
) -> int:
    """One ``max_tokens`` for every selected model.

    An explicit value must fit every model (``invalid_parameter`` otherwise). ``None`` resolves
    to ``min(DEFAULT_MAX_TOKENS, smallest effective max among the models)``.
    """
    smallest = min(effective_max_output_tokens(spec, settings) for spec in specs)
    if requested is None:
        return min(settings.default_max_tokens, smallest)
    if requested > smallest:
        limiting = min(specs, key=lambda spec: effective_max_output_tokens(spec, settings))
        raise invalid_parameter(
            "max_tokens",
            f"max_tokens exceeds the maximum output of {limiting.display_name} ({smallest}).",
            smallest,
        )
    return requested


def single_max_tokens(spec: ModelSpec, settings: Settings, requested: int | None) -> int:
    if requested is None:
        return default_max_tokens_for(spec, settings)
    return resolve_max_tokens([spec], settings, requested)


async def call_generate(
    state: AppState, spec: ModelSpec, request: GenerationRequest
) -> GenerationResult:
    """``provider.generate`` under the global concurrency limit and the request deadline."""
    provider = state.registry.provider_for(spec)
    try:
        async with asyncio.timeout(request.timeout_s), state.provider_semaphore:
            return await provider.generate(request)
    except TimeoutError:
        error = ProviderError(ProviderErrorKind.TIMEOUT, spec.provider)
        log_provider_failure(logger, error, upstream_type="deadline")
        raise error from None
