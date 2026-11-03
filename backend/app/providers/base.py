"""Provider-neutral types shared by every model provider and the services that call them."""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

FinishReason = Literal["stop", "length", "content_filter", "refusal", "other"]

#: Warning attached to results that the model declined to produce.
REFUSAL_WARNING = "The model declined to complete this request."


class ProviderName(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GEMINI = "gemini"
    DEMO = "demo"


PROVIDER_DISPLAY_NAMES: dict[ProviderName, str] = {
    ProviderName.ANTHROPIC: "Anthropic",
    ProviderName.OPENAI: "OpenAI",
    ProviderName.GEMINI: "Google Gemini",
    ProviderName.DEMO: "Demo",
}


class ProviderErrorKind(StrEnum):
    AUTH = "auth"
    RATE_LIMITED = "rate_limited"
    OVERLOADED = "overloaded"
    INVALID_REQUEST = "invalid_request"
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"


_KIND_MESSAGES: dict[ProviderErrorKind, str] = {
    ProviderErrorKind.AUTH: "The {provider} API rejected the configured credentials.",
    ProviderErrorKind.RATE_LIMITED: "The {provider} API rate limit was reached. Try again later.",
    ProviderErrorKind.OVERLOADED: "The {provider} API is temporarily overloaded. Try again later.",
    ProviderErrorKind.INVALID_REQUEST: (
        "The {provider} API rejected the request. Check the model and parameters."
    ),
    ProviderErrorKind.TIMEOUT: "The {provider} API did not respond in time.",
    ProviderErrorKind.PROVIDER_ERROR: "The {provider} API returned an unexpected error.",
}


@dataclass(frozen=True)
class Pricing:
    """USD per million tokens, with an optional long-context tier."""

    input_per_mtok: float
    output_per_mtok: float
    long_context_threshold: int | None = None
    long_context_input_per_mtok: float | None = None
    long_context_output_per_mtok: float | None = None


@dataclass(frozen=True)
class ModelSpec:
    """One entry of the model catalog."""

    id: str
    provider: ProviderName
    display_name: str
    supports_thinking: bool
    thinking_always_on: bool
    supports_temperature: bool
    max_output_tokens: int  # model limit, before the MAX_OUTPUT_TOKENS cap
    context_window: int | None
    pricing: Pricing | None


@dataclass(frozen=True)
class GenerationRequest:
    """A fully resolved request: unsupported parameters are already dropped by the caller."""

    model: ModelSpec
    system: str | None
    prompt: str
    temperature: float | None
    max_tokens: int
    thinking: bool
    timeout_s: float


@dataclass
class GenerationResult:
    text: str
    thinking: str | None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    ttft_ms: int | None
    finish_reason: FinishReason
    request_id: str | None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ThinkingDelta:
    text: str


@dataclass(frozen=True)
class Completed:
    result: GenerationResult


StreamEvent = TextDelta | ThinkingDelta | Completed


class ProviderError(Exception):
    """A provider failure with a safe, provider-neutral message.

    The message never contains upstream text; upstream details are only logged (redacted).
    """

    def __init__(
        self,
        kind: ProviderErrorKind,
        provider: ProviderName,
        *,
        retry_after: float | None = None,
        upstream_status: int | None = None,
        provider_request_id: str | None = None,
        param: str | None = None,
    ) -> None:
        self.kind = ProviderErrorKind(kind)
        self.provider = ProviderName(provider)
        self.retry_after = retry_after
        self.upstream_status = upstream_status
        self.provider_request_id = provider_request_id
        self.param = param
        super().__init__(self.message)

    @property
    def message(self) -> str:
        return _KIND_MESSAGES[self.kind].format(provider=PROVIDER_DISPLAY_NAMES[self.provider])


def log_provider_failure(
    logger: logging.Logger,
    error: ProviderError,
    *,
    upstream_type: str | None = None,
    upstream_message: str | None = None,
) -> None:
    """Log a provider failure server-side (WARNING).

    The upstream message may contain echoed secrets; the log formatter redacts configured secrets
    and key-like patterns from every line before it is written.
    """
    logger.warning(
        "Provider call failed: provider=%s kind=%s status=%s provider_request_id=%s "
        "upstream_type=%s upstream_message=%s",
        error.provider.value,
        error.kind.value,
        error.upstream_status,
        error.provider_request_id,
        upstream_type,
        (upstream_message or "")[:1000],
        extra={
            "provider": error.provider.value,
            "error_kind": error.kind.value,
            "upstream_status": error.upstream_status,
            "provider_request_id": error.provider_request_id,
        },
    )


def estimate_tokens(text: str | None) -> int:
    """Heuristic token estimate: about four characters per token, at least 1 for non-empty text."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def parse_retry_after(value: str | None) -> float | None:
    """Parse a ``retry-after`` header given in seconds (HTTP dates are ignored)."""
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    if seconds != seconds or seconds < 0 or seconds == float("inf"):  # NaN / negative / inf
        return None
    return seconds


class Provider(ABC):
    """Interface implemented by every model provider."""

    name: ProviderName

    @abstractmethod
    def is_configured(self) -> bool:
        """Whether the provider has the credentials it needs."""

    @abstractmethod
    def stream(self, req: GenerationRequest) -> AsyncIterator[StreamEvent]:
        """Yield text/thinking deltas, then exactly one :class:`Completed` as the last item.

        Raises :class:`ProviderError` on failure.
        """

    async def generate(self, req: GenerationRequest) -> GenerationResult:
        """Run a request to completion and return the final result (no time-to-first-token)."""
        result: GenerationResult | None = None
        async for event in self.stream(req):
            if isinstance(event, Completed):
                result = event.result
        if result is None:
            raise ProviderError(ProviderErrorKind.PROVIDER_ERROR, self.name)
        result.ttft_ms = None
        return result

    async def count_tokens(self, req: GenerationRequest) -> int | None:
        """Exact input token count when the provider offers one, else ``None``."""
        return None

    async def aclose(self) -> None:  # noqa: B027 - optional hook, most providers hold no resources
        """Release SDK clients."""
