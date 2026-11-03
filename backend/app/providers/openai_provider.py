"""OpenAI provider (official ``openai`` SDK, ``AsyncOpenAI``, Chat Completions streaming).

This is the only module that imports the OpenAI SDK.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import AsyncIterator
from typing import Any

import openai

from app.providers.base import (
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
    estimate_tokens,
    log_provider_failure,
    parse_retry_after,
)

logger = logging.getLogger(__name__)

_FINISH_REASONS: dict[str, FinishReason] = {
    "stop": "stop",
    "length": "length",
    "content_filter": "content_filter",
}
_PARAM_PATTERN = re.compile(r"^[A-Za-z0-9_.\[\]]{1,64}$")


def build_chat_kwargs(req: GenerationRequest) -> dict[str, Any]:
    """Keyword arguments for ``chat.completions.create`` (streaming with usage)."""
    messages: list[dict[str, str]] = []
    if req.system:
        messages.append({"role": "system", "content": req.system})
    messages.append({"role": "user", "content": req.prompt})
    kwargs: dict[str, Any] = {
        "model": req.model.id,
        "messages": messages,
        "max_completion_tokens": req.max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if req.temperature is not None:
        kwargs["temperature"] = req.temperature
    return kwargs


def map_openai_error(exc: openai.OpenAIError) -> ProviderError:
    """Translate an SDK exception into a :class:`ProviderError`."""
    provider = ProviderName.OPENAI
    if isinstance(exc, openai.APITimeoutError):
        return ProviderError(ProviderErrorKind.TIMEOUT, provider)
    if isinstance(exc, openai.APIConnectionError):
        return ProviderError(ProviderErrorKind.PROVIDER_ERROR, provider)
    if isinstance(exc, openai.APIStatusError):
        status = exc.status_code
        request_id = exc.request_id
        retry_after: float | None = None
        param: str | None = None
        kind: ProviderErrorKind
        if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
            kind = ProviderErrorKind.AUTH
        elif isinstance(exc, openai.RateLimitError):
            if exc.code == "insufficient_quota":
                kind = ProviderErrorKind.AUTH
            else:
                kind = ProviderErrorKind.RATE_LIMITED
                retry_after = parse_retry_after(exc.response.headers.get("retry-after"))
        elif isinstance(
            exc,
            openai.BadRequestError
            | openai.NotFoundError
            | openai.UnprocessableEntityError
            | openai.ConflictError,
        ):
            kind = ProviderErrorKind.INVALID_REQUEST
            if isinstance(exc.param, str) and _PARAM_PATTERN.match(exc.param):
                param = exc.param
        elif isinstance(exc, openai.InternalServerError) and status == 503:
            kind = ProviderErrorKind.OVERLOADED
            retry_after = parse_retry_after(exc.response.headers.get("retry-after"))
        else:
            kind = ProviderErrorKind.PROVIDER_ERROR
        return ProviderError(
            kind,
            provider,
            retry_after=retry_after,
            upstream_status=status,
            provider_request_id=request_id,
            param=param,
        )
    return ProviderError(ProviderErrorKind.PROVIDER_ERROR, provider)


class OpenAIProvider(Provider):
    """OpenAI (or OpenAI-compatible) chat models through ``AsyncOpenAI``."""

    name = ProviderName.OPENAI

    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str | None = None,
        max_retries: int = 2,
        timeout_s: float = 120.0,
        client: openai.AsyncOpenAI | None = None,
    ) -> None:
        self._api_key = api_key or None
        self._base_url = base_url
        self._max_retries = max_retries
        self._timeout_s = timeout_s
        self._client = client

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> openai.AsyncOpenAI:
        if self._client is None:
            self._client = openai.AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url or None,
                max_retries=self._max_retries,
                timeout=self._timeout_s,
            )
        return self._client

    async def stream(self, req: GenerationRequest) -> AsyncIterator[StreamEvent]:
        if not self.is_configured():
            raise ProviderError(ProviderErrorKind.AUTH, self.name)
        kwargs = build_chat_kwargs(req)
        client = self._get_client()
        started = time.monotonic()
        ttft_ms: int | None = None
        parts: list[str] = []
        finish_raw: str | None = None
        usage: Any = None
        chunk_id: str | None = None
        try:
            stream = await client.chat.completions.create(**kwargs)
            request_id = stream.response.headers.get("x-request-id")
            async with stream:
                async for chunk in stream:
                    chunk_id = chunk_id or chunk.id
                    if chunk.usage is not None:
                        usage = chunk.usage
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    if choice.finish_reason:
                        finish_raw = choice.finish_reason
                    content = choice.delta.content if choice.delta is not None else None
                    if content:
                        if ttft_ms is None:
                            ttft_ms = int((time.monotonic() - started) * 1000)
                        parts.append(content)
                        yield TextDelta(content)
        except openai.OpenAIError as exc:
            error = map_openai_error(exc)
            upstream_type = getattr(exc, "type", None) or type(exc).__name__
            log_provider_failure(
                logger,
                error,
                upstream_type=str(upstream_type),
                upstream_message=getattr(exc, "message", None) or str(exc),
            )
            raise error from None
        latency_ms = int((time.monotonic() - started) * 1000)
        text = "".join(parts)
        if usage is not None:
            input_tokens = int(usage.prompt_tokens or 0)
            output_tokens = int(usage.completion_tokens or 0)
        else:
            input_tokens = estimate_tokens(req.system) + estimate_tokens(req.prompt)
            output_tokens = estimate_tokens(text)
        yield Completed(
            GenerationResult(
                text=text,
                thinking=None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                ttft_ms=ttft_ms,
                finish_reason=_FINISH_REASONS.get(finish_raw or "", "other"),
                request_id=request_id or chunk_id,
            )
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
