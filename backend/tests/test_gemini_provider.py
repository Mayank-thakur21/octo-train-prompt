"""Gemini provider: config fields, thought parts, usage, finish reasons and error mapping."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from google import genai
from google.genai import types

from app.config import Settings
from app.providers.base import (
    Completed,
    GenerationRequest,
    ProviderError,
    ProviderErrorKind,
    TextDelta,
    ThinkingDelta,
)
from app.providers.catalog import gemini_models
from app.providers.gemini_provider import GeminiProvider, build_config, map_gemini_error

Handler = Callable[[httpx2.Request], httpx2.Response]


def spec(model_id: str = "gemini-3.5-flash") -> Any:
    settings = Settings(_env_file=None, gemini_models=f"{model_id},gemini-2.0-flash")
    return {item.id: item for item in gemini_models(settings)}[model_id]


class Recorder:
    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.handler(request)


def make_provider(handler: Handler) -> tuple[GeminiProvider, Recorder]:
    recorder = Recorder(handler)
    client = genai.Client(
        api_key="k",
        http_options=types.HttpOptions(
            httpx_async_client=httpx2.AsyncClient(transport=httpx2.MockTransport(recorder))
        ),
    )
    return GeminiProvider("k", client=client), recorder


def sse_handler(chunks: list[dict[str, Any]]) -> Handler:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        data = "".join(f"data: {json.dumps(item)}\r\n\r\n" for item in chunks)
        return httpx2.Response(
            200, content=data.encode(), headers={"content-type": "text/event-stream"}
        )

    return handler


def request_for(
    *, thinking: bool = False, temperature: float | None = None, system: str | None = None
) -> GenerationRequest:
    return GenerationRequest(
        model=spec(),
        system=system,
        prompt="hi",
        temperature=temperature,
        max_tokens=50,
        thinking=thinking,
        timeout_s=30,
    )


CHUNKS = [
    {
        "candidates": [
            {"content": {"role": "model", "parts": [{"text": "Thinking...", "thought": True}]}}
        ],
        "responseId": "resp_1",
    },
    {
        "candidates": [
            {
                "content": {"role": "model", "parts": [{"text": "Hi "}, {"text": ""}]},
            }
        ],
    },
    {
        "candidates": [
            {"content": {"role": "model", "parts": [{"text": "there"}]}, "finishReason": "STOP"}
        ],
        "usageMetadata": {
            "promptTokenCount": 4,
            "candidatesTokenCount": 3,
            "thoughtsTokenCount": 2,
        },
        "responseId": "resp_1",
    },
]


async def test_stream_parsing_thoughts_and_usage() -> None:
    provider, recorder = make_provider(sse_handler(CHUNKS))
    events = [
        event
        async for event in provider.stream(
            request_for(thinking=True, temperature=0.5, system="sys")
        )
    ]
    assert events[:3] == [ThinkingDelta("Thinking..."), TextDelta("Hi "), TextDelta("there")]
    final = events[-1]
    assert isinstance(final, Completed)
    result = final.result
    assert result.text == "Hi there"
    assert result.thinking == "Thinking..."
    assert result.input_tokens == 4
    assert result.output_tokens == 5
    assert result.finish_reason == "stop"
    assert result.request_id == "resp_1"
    request = recorder.requests[0]
    assert request.url.path.endswith(":streamGenerateContent")
    body = json.loads(request.content)
    assert body["generationConfig"]["maxOutputTokens"] == 50
    assert body["generationConfig"]["temperature"] == 0.5
    thinking_config = body["generationConfig"]["thinkingConfig"]
    assert thinking_config.get("includeThoughts", thinking_config.get("include_thoughts")) is True
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"
    await provider.aclose()


def test_build_config_only_sets_requested_fields() -> None:
    config = build_config(request_for())
    dumped = config.model_dump(exclude_none=True)
    assert dumped == {"max_output_tokens": 50}


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("MAX_TOKENS", "length"),
        ("SAFETY", "content_filter"),
        ("RECITATION", "content_filter"),
        ("PROHIBITED_CONTENT", "content_filter"),
        ("OTHER", "other"),
    ],
)
async def test_finish_reasons(reason: str, expected: str) -> None:
    chunks = [
        {
            "candidates": [
                {"content": {"role": "model", "parts": [{"text": "x"}]}, "finishReason": reason}
            ],
        }
    ]
    provider, _ = make_provider(sse_handler(chunks))
    result = await provider.generate(request_for())
    assert result.finish_reason == expected
    # No usage metadata: heuristic estimate.
    assert result.input_tokens == 1
    assert result.output_tokens == 1


async def test_blocked_prompt_is_content_filter() -> None:
    chunks = [{"promptFeedback": {"blockReason": "SAFETY"}, "responseId": "r2"}]
    provider, _ = make_provider(sse_handler(chunks))
    result = await provider.generate(request_for())
    assert result.finish_reason == "content_filter"
    assert result.text == ""
    assert result.request_id == "r2"


def google_error(status: int, reason: str | None = None) -> Handler:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        error: dict[str, Any] = {
            "code": status,
            "message": "AIzaSECRETSECRETSECRETSECRET",
            "status": "X",
        }
        if reason:
            error["details"] = [
                {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason}
            ]
        return httpx2.Response(status, json={"error": error})

    return handler


@pytest.mark.parametrize(
    ("status", "reason", "kind"),
    [
        (400, "API_KEY_INVALID", ProviderErrorKind.AUTH),
        (400, None, ProviderErrorKind.INVALID_REQUEST),
        (401, None, ProviderErrorKind.AUTH),
        (403, None, ProviderErrorKind.AUTH),
        (404, None, ProviderErrorKind.INVALID_REQUEST),
        (429, None, ProviderErrorKind.RATE_LIMITED),
        (500, None, ProviderErrorKind.PROVIDER_ERROR),
        (503, None, ProviderErrorKind.OVERLOADED),
        (504, None, ProviderErrorKind.TIMEOUT),
    ],
)
async def test_error_mapping(status: int, reason: str | None, kind: ProviderErrorKind) -> None:
    provider, _ = make_provider(google_error(status, reason))
    with pytest.raises(ProviderError) as info:
        await provider.generate(request_for())
    assert info.value.kind is kind
    assert info.value.upstream_status == status
    assert "AIza" not in str(info.value)
    assert "Google Gemini" in info.value.message


def test_non_api_errors_are_provider_errors() -> None:
    assert map_gemini_error(RuntimeError("x")).kind is ProviderErrorKind.PROVIDER_ERROR
    from google.genai import errors

    odd = errors.APIError(400, {"error": "not a dict"})
    assert map_gemini_error(odd).kind is ProviderErrorKind.INVALID_REQUEST
    odd_details = errors.APIError(400, {"error": {"details": "nope"}})
    assert map_gemini_error(odd_details).kind is ProviderErrorKind.INVALID_REQUEST
    assert map_gemini_error(errors.APIError(400, ["x"])).kind is ProviderErrorKind.INVALID_REQUEST


async def test_transport_failure_maps_to_provider_error() -> None:
    def broken(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    provider, _ = make_provider(broken)
    with pytest.raises(ProviderError) as info:
        await provider.generate(request_for())
    assert info.value.kind is ProviderErrorKind.PROVIDER_ERROR


async def test_unconfigured_and_lazy_client() -> None:
    provider = GeminiProvider(None)
    assert not provider.is_configured()
    with pytest.raises(ProviderError):
        await provider.generate(request_for())
    configured = GeminiProvider("k", max_retries=0, timeout_s=5)
    client = configured._get_client()
    assert configured._get_client() is client
    await configured.aclose()
    assert configured._client is None


def test_thinking_support_by_model_id() -> None:
    assert spec("gemini-3.5-flash").supports_thinking
    assert not spec("gemini-2.0-flash").supports_thinking
