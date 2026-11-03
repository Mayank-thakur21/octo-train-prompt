"""Provider registry: the model catalog plus one provider instance per provider name."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from pydantic import SecretStr

from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import ModelSpec, Provider, ProviderName
from app.providers.catalog import build_catalog
from app.providers.demo import DemoProvider
from app.providers.gemini_provider import GeminiProvider
from app.providers.openai_provider import OpenAIProvider

if TYPE_CHECKING:
    from app.config import Settings

REAL_PROVIDERS = (ProviderName.ANTHROPIC, ProviderName.OPENAI, ProviderName.GEMINI)


class ProviderRegistry:
    """Catalog lookups and provider access for the services."""

    def __init__(
        self,
        providers: Mapping[ProviderName, Provider],
        catalog: list[ModelSpec],
        default_model: str,
    ) -> None:
        self.providers: dict[ProviderName, Provider] = dict(providers)
        self._catalog = list(catalog)
        self._by_id = {spec.id: spec for spec in self._catalog}
        self._default_model = default_model

    def models(self) -> list[ModelSpec]:
        return list(self._catalog)

    def get_model(self, model_id: str) -> ModelSpec | None:
        return self._by_id.get(model_id)

    def provider_for(self, spec: ModelSpec) -> Provider:
        return self.providers[spec.provider]

    def is_configured(self, name: ProviderName) -> bool:
        provider = self.providers.get(name)
        return provider is not None and provider.is_configured()

    def is_available(self, spec: ModelSpec) -> bool:
        if spec.provider is ProviderName.DEMO:
            return spec.id in self._by_id
        return self.is_configured(spec.provider)

    def effective_default_model(self) -> ModelSpec:
        """The preferred default if available, else the first available model.

        When nothing is available the preferred default is returned and runs fail with
        ``provider_not_configured``.
        """
        preferred = self._by_id[self._default_model]
        if self.is_available(preferred):
            return preferred
        for spec in self._catalog:
            if self.is_available(spec):
                return spec
        return preferred

    def demo_mode(self) -> bool:
        """True when no real (non-demo) provider is configured."""
        return not any(self.is_configured(name) for name in REAL_PROVIDERS)

    async def aclose(self) -> None:
        for provider in self.providers.values():
            await provider.aclose()


def _secret(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value is not None else None


def default_providers(settings: Settings) -> dict[ProviderName, Provider]:
    """Real provider instances built from settings (SDK clients are created lazily)."""
    common = {
        "max_retries": settings.provider_max_retries,
        "timeout_s": settings.request_timeout_seconds,
    }
    return {
        ProviderName.ANTHROPIC: AnthropicProvider(_secret(settings.anthropic_api_key), **common),
        ProviderName.OPENAI: OpenAIProvider(
            _secret(settings.openai_api_key), base_url=settings.openai_base_url, **common
        ),
        ProviderName.GEMINI: GeminiProvider(_secret(settings.gemini_api_key), **common),
        ProviderName.DEMO: DemoProvider(stream_delay_ms=settings.demo_stream_delay_ms),
    }


def build_registry(
    settings: Settings, providers: Mapping[ProviderName, Provider] | None = None
) -> ProviderRegistry:
    """Build the catalog and providers; injected ``providers`` replace the real ones by name.

    Raises ``ValueError`` when ``DEFAULT_MODEL`` or ``JUDGE_MODEL`` is not a catalog id or when
    two catalog entries share an id.
    """
    catalog = build_catalog(settings)
    ids = {spec.id for spec in catalog}
    if settings.default_model not in ids:
        raise ValueError(f"DEFAULT_MODEL {settings.default_model!r} is not in the model catalog")
    if settings.judge_model is not None and settings.judge_model not in ids:
        raise ValueError(f"JUDGE_MODEL {settings.judge_model!r} is not in the model catalog")
    merged = default_providers(settings)
    if providers:
        merged.update(providers)
    return ProviderRegistry(merged, catalog, settings.default_model)
