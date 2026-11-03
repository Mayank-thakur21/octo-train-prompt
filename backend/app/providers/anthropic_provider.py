"""Anthropic Claude provider (official ``anthropic`` SDK, ``AsyncAnthropic``).

This is the only module that imports the Anthropic SDK. Every request streams through
``client.messages.stream()`` and reads the final message with ``get_final_message()``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from app.providers.base import (
    REFUSAL_WARNING,
    Completed,
    FinishReason,
    GenerationRequest,
    GenerationResult,
    Provider,
    ProviderError,
    ProviderErrorKind,
    ProviderName,
    StreamEvent,
    TextDelta,
    ThinkingDelta,
    log_provider_failure,
    parse_retry_after,
)

logger = logging.getLogger(__name__)

#: Thinking setting sent when a run asks for thinking: adaptive with summarized text, so the
#: thinking summary is returned (the API's default ``display`` omits thinking text).
THINKING_ON: dict[str, str] = {"type": "adaptive", "display": "summarized"}

#: Per-model thinking setting when a run does not ask for thinking. ``None`` means the key is
#: omitted: Claude Opus 5.5 and Claude Fable 5.1 always think and reject ``disabled``; Claude
#: Sonnet 5.5 rejects ``disabled`` and uses ``between_tools`` as its lowest setting; Claude
#: Haiku 5.5 accepts ``disabled`` at its default effort.
THINKING_OFF: dict[str, dict[str, str] | None] = {
    "claude-opus-5-5": None,
    "claude-fable-5-1": None,
    "claude-sonnet-5-5": {"type": "between_tools"},
    "claude-haiku-5-5": {"type": "disabled"},
}

_STOP_REASONS: dict[str, FinishReason] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "refusal": "refusal",
}


_ERROR_TYPE_KINDS: dict[str, ProviderErrorKind] = {
    "authentication_error": ProviderErrorKind.AUTH,
    "permission_error": ProviderErrorKind.AUTH,
    "billing_error": ProviderErrorKind.AUTH,
    "rate_limit_error": ProviderErrorKind.RATE_LIMITED,
    "overloaded_error": ProviderErrorKind.OVERLOADED,
    "invalid_request_error": ProviderErrorKind.INVALID_REQUEST,
    "not_found_error": ProviderErrorKind.INVALID_REQUEST,
    "request_too_large": ProviderErrorKind.INVALID_REQUEST,
    "timeout_error": ProviderErrorKind.TIMEOUT,
}


def build_message_kwargs(req: GenerationRequest) -> dict[str, Any]:
    """The exact keyword arguments for ``messages.stream()``.

    Sampling parameters, thinking budgets, effort, tools, prefill and cache control are never
    sent: the API version used by the SDK rejects sampling parameters on every model, and the
    current models reject thinking budgets.
    """
    kwargs: dict[str, Any] = {
        "model": req.model.id,
        "max_tokens": req.max_tokens,
        "messages": [{"role": "user", "content": req.prompt}],
    }
    if req.system:
        kwargs["system"] = req.system
    thinking = dict(THINKING_ON) if req.thinking else THINKING_OFF.get(req.model.id)
    if thinking is not None:
        kwargs["thinking"] = dict(thinking)
    return kwargs


def map_anthropic_error(exc: anthropic.AnthropicError) -> ProviderError:
    """Translate an SDK exception into a :class:`ProviderError` (most specific class first)."""
    provider = ProviderName.ANTHROPIC
    if isinstance(exc, anthropic.APITimeoutError):
        return ProviderError(ProviderErrorKind.TIMEOUT, provider)
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderError(ProviderErrorKind.PROVIDER_ERROR, provider)
    if isinstance(exc, anthropic.APIStatusError):
        status = exc.status_code
        request_id = exc.request_id
        retry_after = parse_retry_after(exc.response.headers.get("retry-after"))
        kind: ProviderErrorKind
        if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError) or (
            status == 402
        ):
            kind = ProviderErrorKind.AUTH
        elif isinstance(exc, anthropic.RateLimitError):
            kind = ProviderErrorKind.RATE_LIMITED
        elif isinstance(exc, anthropic.OverloadedError | anthropic.ServiceUnavailableError):
            kind = ProviderErrorKind.OVERLOADED
        elif isinstance(exc, anthropic.DeadlineExceededError):
            kind = ProviderErrorKind.TIMEOUT
        elif isinstance(
            exc,
            anthropic.BadRequestError
            | anthropic.NotFoundError
            | anthropic.RequestTooLargeError
            | anthropic.UnprocessableEntityError
            | anthropic.ConflictError,
        ):
            kind = ProviderErrorKind.INVALID_REQUEST
        elif status == 503:
            # The SDK raises InternalServerError for 503/504 responses.
            kind = ProviderErrorKind.OVERLOADED
        elif status == 504:
            kind = ProviderErrorKind.TIMEOUT
        else:
            # Errors sent inside an event stream arrive with the stream's 200 status; their
            # error type says what happened.
            kind = _ERROR_TYPE_KINDS.get(str(exc.type), ProviderErrorKind.PROVIDER_ERROR)
        keep_retry = kind in {ProviderErrorKind.RATE_LIMITED, ProviderErrorKind.OVERLOADED}
        return ProviderError(
            kind,
            provider,
            retry_after=retry_after if keep_retry else None,
            upstream_status=status,
            provider_request_id=request_id,
        )
    return ProviderError(ProviderErrorKind.PROVIDER_ERROR, provider)


def _log_sdk_error(exc: anthropic.AnthropicError, error: ProviderError) -> None:
    upstream_type = (
        getattr(exc, "type", None) if isinstance(exc, anthropic.APIStatusError) else None
    )
    log_provider_failure(
        logger,
        error,
        upstream_type=upstream_type or type(exc).__name__,
        upstream_message=getattr(exc, "message", None) or str(exc),
    )


class AnthropicProvider(Provider):
    """Claude models through ``AsyncAnthropic``."""

    name = ProviderName.ANTHROPIC

    def __init__(
        self,
        api_key: str | None,
        *,
        max_retries: int = 2,
        timeout_s: float = 120.0,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self._api_key = api_key or None
        self._max_retries = max_retries
        self._timeout_s = timeout_s
        self._client = client

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            # The key is passed explicitly so the SDK never falls back to environment variables
            # or on-disk credential profiles.
            self._client = anthropic.AsyncAnthropic(
                api_key=self._api_key,
                max_retries=self._max_retries,
                timeout=self._timeout_s,
            )
        return self._client

    async def stream(self, req: GenerationRequest) -> AsyncIterator[StreamEvent]:
        if not self.is_configured():
            raise ProviderError(ProviderErrorKind.AUTH, self.name)
        kwargs = build_message_kwargs(req)
        client = self._get_client()
        started = time.monotonic()
        ttft_ms: int | None = None
        try:
            async with client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type != "content_block_delta":
                        continue
                    delta = event.delta
                    if delta.type == "text_delta" and delta.text:
                        if ttft_ms is None:
                            ttft_ms = int((time.monotonic() - started) * 1000)
                        yield TextDelta(delta.text)
                    elif delta.type == "thinking_delta" and delta.thinking:
                        if ttft_ms is None:
                            ttft_ms = int((time.monotonic() - started) * 1000)
                        yield ThinkingDelta(delta.thinking)
                final = await stream.get_final_message()
                request_id = stream.request_id
        except anthropic.AnthropicError as exc:
            error = map_anthropic_error(exc)
            _log_sdk_error(exc, error)
            raise error from None
        latency_ms = int((time.monotonic() - started) * 1000)

        # The final message accumulates exactly the streamed deltas, so this equals their
        # concatenation.
        text = "".join(block.text for block in final.content if block.type == "text")
        thinking_parts = [
            block.thinking for block in final.content if block.type == "thinking" and block.thinking
        ]
        usage = final.usage
        input_tokens = (
            usage.input_tokens
            + (usage.cache_creation_input_tokens or 0)
            + (usage.cache_read_input_tokens or 0)
        )
        finish = _STOP_REASONS.get(final.stop_reason or "", "other")
        warnings = [REFUSAL_WARNING] if finish == "refusal" else []
        yield Completed(
            GenerationResult(
                text=text,
                thinking="\n\n".join(thinking_parts) if thinking_parts else None,
                input_tokens=input_tokens,
                output_tokens=usage.output_tokens,
                latency_ms=latency_ms,
                ttft_ms=ttft_ms,
                finish_reason=finish,
                request_id=request_id,
                warnings=warnings,
            )
        )

    async def count_tokens(self, req: GenerationRequest) -> int | None:
        """Exact input tokens from ``messages.count_tokens``; ``None`` on any failure."""
        if not self.is_configured():
            return None
        kwargs: dict[str, Any] = {
            "model": req.model.id,
            "messages": [{"role": "user", "content": req.prompt}],
        }
        if req.system:
            kwargs["system"] = req.system
        try:
            result = await self._get_client().messages.count_tokens(**kwargs)
        except anthropic.AnthropicError as exc:
            _log_sdk_error(exc, map_anthropic_error(exc))
            return None
        return int(result.input_tokens)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
