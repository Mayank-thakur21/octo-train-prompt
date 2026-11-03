"""Google Gemini provider (current ``google-genai`` SDK, async client).

This is the only module that imports ``google.genai``.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

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
    ThinkingDelta,
    estimate_tokens,
    log_provider_failure,
)

logger = logging.getLogger(__name__)

_CONTENT_FILTER_REASONS = frozenset(
    {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY"}
)
_INVALID_REQUEST_CODES = frozenset({400, 404, 409, 413, 422})


def build_config(req: GenerationRequest) -> types.GenerateContentConfig:
    """Generation config containing only the fields this app controls."""
    fields: dict[str, Any] = {"max_output_tokens": req.max_tokens}
    if req.system:
        fields["system_instruction"] = req.system
    if req.temperature is not None:
        fields["temperature"] = req.temperature
    if req.thinking:
        fields["thinking_config"] = types.ThinkingConfig(include_thoughts=True)
    return types.GenerateContentConfig(**fields)


def _is_api_key_invalid(details: Any) -> bool:
    """Whether a Google error body carries ``reason: API_KEY_INVALID``."""
    if not isinstance(details, dict):
        return False
    error = details.get("error")
    if not isinstance(error, dict):
        return False
    items = error.get("details")
    if not isinstance(items, list):
        return False
    return any(isinstance(item, dict) and item.get("reason") == "API_KEY_INVALID" for item in items)


def map_gemini_error(exc: Exception) -> ProviderError:
    """Translate an SDK exception into a :class:`ProviderError`."""
    provider = ProviderName.GEMINI
    if not isinstance(exc, genai_errors.APIError):
        return ProviderError(ProviderErrorKind.PROVIDER_ERROR, provider)
    code = exc.code if isinstance(exc.code, int) else None
    kind: ProviderErrorKind
    if code in {401, 403} or (code == 400 and _is_api_key_invalid(exc.details)):
        kind = ProviderErrorKind.AUTH
    elif code in _INVALID_REQUEST_CODES:
        kind = ProviderErrorKind.INVALID_REQUEST
    elif code == 429:
        kind = ProviderErrorKind.RATE_LIMITED
    elif code == 503:
        kind = ProviderErrorKind.OVERLOADED
    elif code == 504:
        kind = ProviderErrorKind.TIMEOUT
    else:
        kind = ProviderErrorKind.PROVIDER_ERROR
    return ProviderError(kind, provider, upstream_status=code)


def _finish_reason(raw: str | None, blocked: bool) -> FinishReason:
    if raw == "STOP":
        return "stop"
    if raw == "MAX_TOKENS":
        return "length"
    if raw in _CONTENT_FILTER_REASONS or (raw is None and blocked):
        return "content_filter"
    return "other"


class GeminiProvider(Provider):
    """Gemini models through ``genai.Client(...).aio``."""

    name = ProviderName.GEMINI

    def __init__(
        self,
        api_key: str | None,
        *,
        max_retries: int = 2,
        timeout_s: float = 120.0,
        client: genai.Client | None = None,
    ) -> None:
        self._api_key = api_key or None
        self._max_retries = max_retries
        self._timeout_s = timeout_s
        self._client = client

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(
                api_key=self._api_key,
                vertexai=False,
                http_options=types.HttpOptions(
                    timeout=int(self._timeout_s * 1000),
                    retry_options=types.HttpRetryOptions(attempts=self._max_retries + 1),
                ),
            )
        return self._client

    async def stream(self, req: GenerationRequest) -> AsyncIterator[StreamEvent]:
        if not self.is_configured():
            raise ProviderError(ProviderErrorKind.AUTH, self.name)
        client = self._get_client()
        config = build_config(req)
        started = time.monotonic()
        ttft_ms: int | None = None
        parts_text: list[str] = []
        thoughts: list[str] = []
        usage: Any = None
        response_id: str | None = None
        finish_raw: str | None = None
        saw_candidates = False
        blocked = False
        try:
            response_stream = await client.aio.models.generate_content_stream(
                model=req.model.id, contents=req.prompt, config=config
            )
            async with contextlib.aclosing(response_stream) as chunks:
                async for chunk in chunks:
                    response_id = chunk.response_id or response_id
                    if chunk.usage_metadata is not None:
                        usage = chunk.usage_metadata
                    feedback = chunk.prompt_feedback
                    if feedback is not None and feedback.block_reason:
                        blocked = True
                    if not chunk.candidates:
                        continue
                    saw_candidates = True
                    candidate = chunk.candidates[0]
                    if candidate.finish_reason is not None:
                        reason = candidate.finish_reason
                        finish_raw = str(getattr(reason, "value", reason))
                    content_parts = candidate.content.parts if candidate.content else None
                    for part in content_parts or []:
                        if not part.text:
                            continue
                        if ttft_ms is None:
                            ttft_ms = int((time.monotonic() - started) * 1000)
                        if part.thought:
                            thoughts.append(part.text)
                            yield ThinkingDelta(part.text)
                        else:
                            parts_text.append(part.text)
                            yield TextDelta(part.text)
        except Exception as exc:  # the SDK raises APIError subclasses and transport errors
            error = map_gemini_error(exc)
            log_provider_failure(
                logger,
                error,
                upstream_type=getattr(exc, "status", None) or type(exc).__name__,
                upstream_message=getattr(exc, "message", None) or str(exc),
            )
            raise error from None
        latency_ms = int((time.monotonic() - started) * 1000)
        text = "".join(parts_text)
        if usage is not None and usage.prompt_token_count is not None:
            input_tokens = int(usage.prompt_token_count)
            output_tokens = int(usage.candidates_token_count or 0) + int(
                usage.thoughts_token_count or 0
            )
        else:
            input_tokens = estimate_tokens(req.system) + estimate_tokens(req.prompt)
            output_tokens = estimate_tokens(text)
        yield Completed(
            GenerationResult(
                text=text,
                thinking="".join(thoughts) or None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                ttft_ms=ttft_ms,
                finish_reason=_finish_reason(finish_raw, blocked and not saw_candidates),
                request_id=response_id,
            )
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aio.aclose()
            self._client = None
