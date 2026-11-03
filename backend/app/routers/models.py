"""The model catalog."""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import AuthFirstRoute, RegistryDep, SettingsDep, guard
from app.providers.base import ModelSpec
from app.providers.catalog import effective_max_output_tokens
from app.schemas import LongContextPricing, ModelInfo, ModelsResponse, PricingOut

router = APIRouter(prefix="/api", route_class=AuthFirstRoute, tags=["models"])


def _pricing(spec: ModelSpec) -> PricingOut | None:
    pricing = spec.pricing
    if pricing is None:
        return None
    long_context = None
    if (
        pricing.long_context_threshold is not None
        and pricing.long_context_input_per_mtok is not None
        and pricing.long_context_output_per_mtok is not None
    ):
        long_context = LongContextPricing(
            threshold_input_tokens=pricing.long_context_threshold,
            input_per_mtok=pricing.long_context_input_per_mtok,
            output_per_mtok=pricing.long_context_output_per_mtok,
        )
    return PricingOut(
        input_per_mtok=pricing.input_per_mtok,
        output_per_mtok=pricing.output_per_mtok,
        long_context=long_context,
    )


@router.get("/models", response_model=ModelsResponse, dependencies=[guard("default")])
async def list_models(registry: RegistryDep, settings: SettingsDep) -> ModelsResponse:
    """Every catalog model with availability, capabilities, limits and pricing."""
    default = registry.effective_default_model()
    return ModelsResponse(
        models=[
            ModelInfo(
                id=spec.id,
                provider=spec.provider.value,
                display_name=spec.display_name,
                available=registry.is_available(spec),
                is_default=spec.id == default.id,
                supports_thinking=spec.supports_thinking,
                thinking_always_on=spec.thinking_always_on,
                supports_temperature=spec.supports_temperature,
                max_output_tokens=effective_max_output_tokens(spec, settings),
                context_window=spec.context_window,
                pricing=_pricing(spec),
            )
            for spec in registry.models()
        ],
        default_model=default.id,
    )
