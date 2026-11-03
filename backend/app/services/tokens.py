"""Token estimates (heuristic or exact) and the token-estimate endpoint logic."""

from __future__ import annotations

import asyncio
import logging

from app.providers.base import (
    GenerationRequest,
    ProviderError,
    ProviderName,
    estimate_tokens,
)
from app.providers.catalog import default_max_tokens_for
from app.schemas import TokenEstimate, TokenEstimateRequest
from app.services import templating
from app.services.common import resolve_model_id
from app.services.validation import check_template, check_variables
from app.state import AppState

logger = logging.getLogger(__name__)

EXACT_COUNT_FAILED = "Exact count unavailable; showing a heuristic estimate."

__all__ = ["EXACT_COUNT_FAILED", "estimate", "estimate_request", "estimate_tokens_for"]


def estimate(text: str | None) -> int:
    """``0`` for empty text, else ``max(1, ceil(len(text) / 4))``."""
    return estimate_tokens(text)


def estimate_request(system: str | None, prompt: str) -> int:
    return estimate(system) + estimate(prompt)


async def estimate_tokens_for(state: AppState, req: TokenEstimateRequest) -> TokenEstimate:
    """Render leniently, then count exactly for configured Anthropic models, else estimate."""
    settings = state.settings
    check_template(settings, system=req.system, prompt=req.prompt)
    check_variables(settings, req.variables)
    spec = resolve_model_id(state, req.model, require_available=False)
    rendered = templating.render(req.system, req.prompt, req.variables)
    system = templating.normalize_system(rendered.system)
    combined = f"{system}\n{rendered.prompt}" if system else rendered.prompt
    warnings: list[str] = []
    method = "heuristic"
    tokens: int | None = None
    if spec.provider is ProviderName.ANTHROPIC and state.registry.is_configured(spec.provider):
        provider = state.registry.provider_for(spec)
        request = GenerationRequest(
            model=spec,
            system=system,
            prompt=rendered.prompt,
            temperature=None,
            max_tokens=default_max_tokens_for(spec, settings),
            thinking=False,
            timeout_s=settings.request_timeout_seconds,
        )
        try:
            async with asyncio.timeout(settings.request_timeout_seconds):
                async with state.provider_semaphore:
                    tokens = await provider.count_tokens(request)
        except (TimeoutError, ProviderError):
            logger.warning("Exact token count failed for model %s", spec.id)
            tokens = None
        if tokens is None:
            warnings.append(EXACT_COUNT_FAILED)
        else:
            method = "anthropic_count_tokens"
    if tokens is None:
        tokens = estimate_request(system, rendered.prompt)
    return TokenEstimate(
        model=spec.id,
        provider=spec.provider.value,
        input_tokens=tokens,
        method=method,
        characters=len(combined),
        words=len(combined.split()),
        warnings=warnings,
    )
