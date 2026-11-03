"""Anthropic provider: exact request bodies, stream parsing, token counting and error mapping."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import pytest

from app.providers.anthropic_provider import AnthropicProvider, build_message_kwargs
from app.providers.base import (
    REFUSAL_WARNING,
    Completed,
    GenerationRequest,
    ProviderError,
    ProviderErrorKind,
    TextDelta,
    ThinkingDelta,
)
from app.providers.catalog import ANTHROPIC_MODELS

SPECS = {spec.id: spec for spec in ANTHROPIC_MODELS}


def sse(events: list[tuple[str, dict[str, Any]]]) -> bytes:
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


def message_events(
    *,
    text_chunks: tuple[str, ...] = ("Hello", " world"),
    thinking: str | None = "Considering.",
    stop_reason: str = "end_turn",
    usage: dict[str, Any] | None = None,
) -> bytes:
    start_usage = {"input_tokens": 12, "output_tokens": 1}
    start_usage.update(usage or {})
    events: list[tuple[str, dict[str, Any]]] = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-opus-5-5",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": start_usage,
                },
            },
        )
    ]
    index = 0
    if thinking is not None:
        events += [
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": index,
                    "content_block": {"type": "thinking", "thinking": "", "signature": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "thinking_delta", "thinking": thinking},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "signature_delta", "signature": "sig"},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": index}),
        ]
        index += 1
    events.append(
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": index,
                "content_block": {"type": "text", "text": ""},
            },
        )
    )
    for chunk in text_chunks:
        events.append(
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "text_delta", "text": chunk},
                },
            )
        )
    events += [
        ("content_block_stop", {"type": "content_block_stop", "index": index}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": 9},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return sse(events)


Handler = Callable[[httpx2.Request], httpx2.Response]


class Recorder:
    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.handler(request)

    def body(self, index: int = 0) -> dict[str, Any]:
        return json.loads(self.requests[index].content)


def make_provider(handler: Handler) -> tuple[AnthropicProvider, Recorder]:
    recorder = Recorder(handler)
    client = anthropic.AsyncAnthropic(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(recorder)),
    )
    return AnthropicProvider("test-key", client=client), recorder


def stream_handler(body: bytes, request_id: str = "req_abc") -> Handler:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            content=body,
            headers={"content-type": "text/event-stream", "request-id": request_id},
        )

    return handler


def request_for(
    model_id: str, *, thinking: bool, system: str | None = "Be brief."
) -> GenerationRequest:
    return GenerationRequest(
        model=SPECS[model_id],
        system=system,
        prompt="Hello?",
        temperature=None,
        max_tokens=256,
        thinking=thinking,
        timeout_s=30,
    )


async def collect(provider: AnthropicProvider, req: GenerationRequest) -> list[Any]:
    return [event async for event in provider.stream(req)]


EXPECTED_THINKING_OFF = {
    "claude-opus-5-5": None,
    "claude-fable-5-1": None,
    "claude-sonnet-5-5": {"type": "between_tools"},
    "claude-haiku-5-5": {"type": "disabled"},
}


@pytest.mark.parametrize("model_id", list(SPECS))
@pytest.mark.parametrize("thinking", [True, False])
async def test_request_body_per_model(model_id: str, thinking: bool) -> None:
    provider, recorder = make_provider(stream_handler(message_events()))
    await collect(provider, request_for(model_id, thinking=thinking))
    body = recorder.body()
    assert body["model"] == model_id
    assert body["max_tokens"] == 256
    assert body["messages"] == [{"role": "user", "content": "Hello?"}]
    assert body["system"] == "Be brief."
    assert body["stream"] is True
    for forbidden in ("temperature", "top_p", "top_k", "output_config", "tools", "cache_control"):
        assert forbidden not in body
    if thinking:
        assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    elif EXPECTED_THINKING_OFF[model_id] is None:
        assert "thinking" not in body
    else:
        assert body["thinking"] == EXPECTED_THINKING_OFF[model_id]
    assert "budget_tokens" not in json.dumps(body)
    await provider.aclose()


def test_system_omitted_when_empty() -> None:
    kwargs = build_message_kwargs(request_for("claude-haiku-5-5", thinking=False, system=None))
    assert "system" not in kwargs
    assert sorted(kwargs) == ["max_tokens", "messages", "model", "thinking"]


async def test_stream_parsing_usage_and_request_id() -> None:
    body = message_events(usage={"cache_creation_input_tokens": 3, "cache_read_input_tokens": 5})
    provider, recorder = make_provider(stream_handler(body, request_id="req_xyz"))
    events = await collect(provider, request_for("claude-opus-5-5", thinking=True))
    assert events[0] == ThinkingDelta("Considering.")
    assert events[1:3] == [TextDelta("Hello"), TextDelta(" world")]
    final = events[-1]
    assert isinstance(final, Completed)
    result = final.result
    assert result.text == "Hello world"
    assert result.thinking == "Considering."
    assert result.input_tokens == 12 + 3 + 5
    assert result.output_tokens == 9
    assert result.finish_reason == "stop"
    assert result.request_id == "req_xyz"
    assert result.ttft_ms is not None
    assert result.warnings == []
    headers = recorder.requests[0].headers
    assert headers["anthropic-version"]
    await provider.aclose()


@pytest.mark.parametrize(
    ("stop_reason", "finish"),
    [
        ("end_turn", "stop"),
        ("stop_sequence", "stop"),
        ("max_tokens", "length"),
        ("refusal", "refusal"),
        ("pause_turn", "other"),
    ],
)
async def test_stop_reasons(stop_reason: str, finish: str) -> None:
    provider, _ = make_provider(
        stream_handler(message_events(stop_reason=stop_reason, thinking=None))
    )
    result = await provider.generate(request_for("claude-sonnet-5-5", thinking=False))
    assert result.finish_reason == finish
    assert result.ttft_ms is None
    assert result.thinking is None
    assert result.warnings == ([REFUSAL_WARNING] if finish == "refusal" else [])


async def test_count_tokens() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path.endswith("/v1/messages/count_tokens")
        return httpx2.Response(200, json={"input_tokens": 42})

    provider, recorder = make_provider(handler)
    count = await provider.count_tokens(request_for("claude-opus-5-5", thinking=False))
    assert count == 42
    body = recorder.body()
    assert body == {
        "model": "claude-opus-5-5",
        "messages": [{"role": "user", "content": "Hello?"}],
        "system": "Be brief.",
    }
    no_system = await provider.count_tokens(
        request_for("claude-opus-5-5", thinking=False, system=None)
    )
    assert no_system == 42
    assert "system" not in recorder.body(1)


async def test_count_tokens_failure_returns_none(caplog: pytest.LogCaptureFixture) -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            500, json={"type": "error", "error": {"type": "api_error", "message": "boom"}}
        )

    provider, _ = make_provider(handler)
    assert await provider.count_tokens(request_for("claude-opus-5-5", thinking=False)) is None
    assert "Provider call failed" in caplog.text


async def test_unconfigured_provider() -> None:
    provider = AnthropicProvider(None)
    assert not provider.is_configured()
    assert await provider.count_tokens(request_for("claude-opus-5-5", thinking=False)) is None
    with pytest.raises(ProviderError) as info:
        await provider.generate(request_for("claude-opus-5-5", thinking=False))
    assert info.value.kind is ProviderErrorKind.AUTH
    await provider.aclose()


async def test_lazy_client_uses_explicit_key() -> None:
    provider = AnthropicProvider("sk-ant-test-key-123456", max_retries=1, timeout_s=9)
    client = provider._get_client()
    assert client.api_key == "sk-ant-test-key-123456"
    assert client.max_retries == 1
    assert provider._get_client() is client
    await provider.aclose()
    assert provider._client is None


def error_handler(status: int, error_type: str, headers: dict[str, str] | None = None) -> Handler:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            status,
            json={
                "type": "error",
                "error": {"type": error_type, "message": "upstream says sk-ant-secretsecret"},
            },
            headers={"request-id": "req_err", **(headers or {})},
        )

    return handler


@pytest.mark.parametrize(
    ("status", "error_type", "kind", "retry_after"),
    [
        (400, "invalid_request_error", ProviderErrorKind.INVALID_REQUEST, None),
        (401, "authentication_error", ProviderErrorKind.AUTH, None),
        (402, "billing_error", ProviderErrorKind.AUTH, None),
        (403, "permission_error", ProviderErrorKind.AUTH, None),
        (404, "not_found_error", ProviderErrorKind.INVALID_REQUEST, None),
        (409, "conflict_error", ProviderErrorKind.INVALID_REQUEST, None),
        (413, "request_too_large", ProviderErrorKind.INVALID_REQUEST, None),
        (422, "invalid_request_error", ProviderErrorKind.INVALID_REQUEST, None),
        (429, "rate_limit_error", ProviderErrorKind.RATE_LIMITED, 12.0),
        (500, "api_error", ProviderErrorKind.PROVIDER_ERROR, None),
        (503, "overloaded_error", ProviderErrorKind.OVERLOADED, 12.0),
        (504, "timeout_error", ProviderErrorKind.TIMEOUT, None),
        (529, "overloaded_error", ProviderErrorKind.OVERLOADED, 12.0),
        (418, "teapot_error", ProviderErrorKind.PROVIDER_ERROR, None),
    ],
)
async def test_error_mapping(
    status: int,
    error_type: str,
    kind: ProviderErrorKind,
    retry_after: float | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider, _ = make_provider(error_handler(status, error_type, {"retry-after": "12"}))
    with pytest.raises(ProviderError) as info:
        await provider.generate(request_for("claude-opus-5-5", thinking=False))
    error = info.value
    assert error.kind is kind
    assert error.upstream_status == status
    assert error.provider_request_id == "req_err"
    assert error.retry_after == retry_after
    assert "upstream says" not in str(error)
    assert "Anthropic" in error.message
    assert "Provider call failed" in caplog.text


async def test_connection_and_timeout_errors() -> None:
    def broken(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    def slow(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    provider, _ = make_provider(broken)
    with pytest.raises(ProviderError) as info:
        await provider.generate(request_for("claude-opus-5-5", thinking=False))
    assert info.value.kind is ProviderErrorKind.PROVIDER_ERROR

    provider, _ = make_provider(slow)
    with pytest.raises(ProviderError) as info:
        await provider.generate(request_for("claude-opus-5-5", thinking=False))
    assert info.value.kind is ProviderErrorKind.TIMEOUT


def test_non_status_sdk_errors_map_to_provider_error() -> None:
    from app.providers.anthropic_provider import map_anthropic_error

    error = map_anthropic_error(anthropic.AnthropicError("odd"))
    assert error.kind is ProviderErrorKind.PROVIDER_ERROR
    assert error.upstream_status is None


async def test_invalid_retry_after_header_is_ignored() -> None:
    provider, _ = make_provider(error_handler(429, "rate_limit_error", {"retry-after": "soon"}))
    with pytest.raises(ProviderError) as info:
        await provider.generate(request_for("claude-opus-5-5", thinking=False))
    assert info.value.retry_after is None


async def test_error_event_inside_stream_maps_by_error_type() -> None:
    body = message_events(text_chunks=("Partial",), thinking=None).split(b"event: message_delta")[0]
    body += sse(
        [
            (
                "error",
                {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}},
            )
        ]
    )
    provider, _ = make_provider(stream_handler(body))
    seen: list[Any] = []

    async def consume() -> None:
        async for event in provider.stream(request_for("claude-opus-5-5", thinking=False)):
            seen.append(event)

    with pytest.raises(ProviderError) as info:
        await consume()
    assert seen == [TextDelta("Partial")]
    assert info.value.kind is ProviderErrorKind.OVERLOADED
    assert info.value.upstream_status == 200
