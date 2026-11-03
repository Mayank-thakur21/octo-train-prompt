"""The model catalog: fixed Anthropic models, OpenAI/Gemini models from settings, demo models."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.providers.base import ModelSpec, Pricing, ProviderName

if TYPE_CHECKING:
    from app.config import Settings

MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_GEMINI_NO_THINKING = re.compile(r"^gemini-(1\.|2\.0)")

#: Anthropic models, in catalog order. Prices are USD per million tokens.
ANTHROPIC_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="claude-opus-5-5",
        provider=ProviderName.ANTHROPIC,
        display_name="Claude Opus 5.5",
        supports_thinking=True,
        thinking_always_on=True,
        supports_temperature=False,
        max_output_tokens=128_000,
        context_window=1_000_000,
        pricing=Pricing(input_per_mtok=4.0, output_per_mtok=20.0),
    ),
    ModelSpec(
        id="claude-sonnet-5-5",
        provider=ProviderName.ANTHROPIC,
        display_name="Claude Sonnet 5.5",
        supports_thinking=True,
        thinking_always_on=False,
        supports_temperature=False,
        max_output_tokens=128_000,
        context_window=1_000_000,
        pricing=Pricing(input_per_mtok=2.0, output_per_mtok=10.0),
    ),
    ModelSpec(
        id="claude-haiku-5-5",
        provider=ProviderName.ANTHROPIC,
        display_name="Claude Haiku 5.5",
        supports_thinking=True,
        thinking_always_on=False,
        supports_temperature=False,
        max_output_tokens=128_000,
        context_window=1_000_000,
        pricing=Pricing(
            input_per_mtok=0.10,
            output_per_mtok=0.50,
            long_context_threshold=100_000,
            long_context_input_per_mtok=0.50,
            long_context_output_per_mtok=2.50,
        ),
    ),
    ModelSpec(
        id="claude-fable-5-1",
        provider=ProviderName.ANTHROPIC,
        display_name="Claude Fable 5.1",
        supports_thinking=True,
        thinking_always_on=True,
        supports_temperature=False,
        max_output_tokens=128_000,
        context_window=1_000_000,
        pricing=Pricing(input_per_mtok=10.0, output_per_mtok=50.0),
    ),
)

DEMO_MAX_OUTPUT_TOKENS = 4096
DEMO_MODELS: tuple[ModelSpec, ...] = tuple(
    ModelSpec(
        id=model_id,
        provider=ProviderName.DEMO,
        display_name=display_name,
        supports_thinking=True,
        thinking_always_on=False,
        supports_temperature=True,
        max_output_tokens=DEMO_MAX_OUTPUT_TOKENS,
        context_window=None,
        pricing=None,
    )
    for model_id, display_name in (
        ("demo-concise", "Demo Concise (offline)"),
        ("demo-verbose", "Demo Verbose (offline)"),
    )
)


def parse_model_entries(entries: list[str]) -> list[tuple[str, str | None]]:
    """Parse ``id`` / ``id=Display Name`` entries; raises ``ValueError`` for an invalid id."""
    parsed: list[tuple[str, str | None]] = []
    for entry in entries:
        model_id, sep, display = entry.partition("=")
        model_id = model_id.strip()
        display_name = display.strip() if sep else ""
        if not MODEL_ID_PATTERN.match(model_id):
            raise ValueError(f"invalid model id in model list: {model_id!r}")
        parsed.append((model_id, display_name or None))
    return parsed


def openai_display_name(model_id: str) -> str:
    """``gpt-5.4-mini`` -> ``GPT-5.4 mini``; ids without the ``gpt-`` prefix are kept."""
    if not model_id.startswith("gpt-"):
        return model_id
    segments = model_id.split("-")
    name = "GPT-" + segments[1]
    rest = segments[2:]
    return " ".join([name, *rest]) if rest else name


def gemini_display_name(model_id: str) -> str:
    """``gemini-3.1-pro-preview`` -> ``Gemini 3.1 Pro Preview``."""
    return " ".join(segment[:1].upper() + segment[1:] for segment in model_id.split("-"))


def openai_models(settings: Settings) -> list[ModelSpec]:
    specs: list[ModelSpec] = []
    for model_id, display in parse_model_entries(settings.openai_models):
        specs.append(
            ModelSpec(
                id=model_id,
                provider=ProviderName.OPENAI,
                display_name=display or openai_display_name(model_id),
                supports_thinking=False,
                thinking_always_on=False,
                supports_temperature=any(
                    model_id.startswith(prefix) for prefix in settings.openai_temperature_prefixes
                ),
                max_output_tokens=settings.openai_max_output_tokens,
                context_window=None,
                pricing=None,
            )
        )
    return specs


def gemini_models(settings: Settings) -> list[ModelSpec]:
    specs: list[ModelSpec] = []
    for model_id, display in parse_model_entries(settings.gemini_models):
        specs.append(
            ModelSpec(
                id=model_id,
                provider=ProviderName.GEMINI,
                display_name=display or gemini_display_name(model_id),
                supports_thinking=not _GEMINI_NO_THINKING.match(model_id),
                thinking_always_on=False,
                supports_temperature=True,
                max_output_tokens=settings.gemini_max_output_tokens,
                context_window=None,
                pricing=None,
            )
        )
    return specs


def build_catalog(settings: Settings) -> list[ModelSpec]:
    """Catalog in API order: Anthropic, OpenAI, Gemini, then demo (when enabled).

    Raises ``ValueError`` when two entries share an id.
    """
    catalog = [*ANTHROPIC_MODELS, *openai_models(settings), *gemini_models(settings)]
    if settings.demo_enabled:
        catalog.extend(DEMO_MODELS)
    seen: set[str] = set()
    for spec in catalog:
        if spec.id in seen:
            raise ValueError(f"duplicate model id in the catalog: {spec.id!r}")
        seen.add(spec.id)
    return catalog


def effective_max_output_tokens(spec: ModelSpec, settings: Settings) -> int:
    """``min(model limit, MAX_OUTPUT_TOKENS)``."""
    return min(spec.max_output_tokens, settings.max_output_tokens)


def default_max_tokens_for(spec: ModelSpec, settings: Settings) -> int:
    """Default ``max_tokens`` when a request leaves it null."""
    return min(settings.default_max_tokens, effective_max_output_tokens(spec, settings))


def compute_cost(pricing: Pricing | None, input_tokens: int, output_tokens: int) -> float | None:
    """USD cost rounded to 6 decimals, using long-context prices above the threshold."""
    if pricing is None:
        return None
    in_price, out_price = pricing.input_per_mtok, pricing.output_per_mtok
    if (
        pricing.long_context_threshold is not None
        and input_tokens > pricing.long_context_threshold
        and pricing.long_context_input_per_mtok is not None
        and pricing.long_context_output_per_mtok is not None
    ):
        in_price = pricing.long_context_input_per_mtok
        out_price = pricing.long_context_output_per_mtok
    cost = input_tokens / 1e6 * in_price + output_tokens / 1e6 * out_price
    return round(cost, 6)
