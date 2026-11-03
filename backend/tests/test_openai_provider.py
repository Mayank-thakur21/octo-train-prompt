"""OpenAI provider: request body, temperature handling, stream parsing and error mapping."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx2
import openai
import pytest

from app.config import Settings
from app.providers.base import (
    Completed,
    GenerationRequest,
    ProviderError,
    ProviderErrorKind,
    TextDelta,
)
from app.providers.catalog import openai_models
from app.providers.openai_provider import OpenAIProvider, map_openai_error

Handler = Callable[[httpx2.Request], httpx2.Response]


def specs() -> dict[str, Any]:
    settings = Settings(_env_file=None, openai_models="gpt-5.5,gpt-4.1-mini")
    return {spec.id: spec for spec in openai_models(settings)}


def chunk(content: str | None, finish: str | None = None, *, cid: str = "chatcmpl-1") -> dict:
    delta = {"content": content} if content is not None else {}
    return {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "gpt-5.5",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


USAGE_CHUNK = {
    "id": "chatcmpl-1",
    "object": "chat.completion.chunk",
    "created": 1,
    "model": "gpt-5.5",
    "choices": [],
    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
}


def stream_body(chunks: list[dict]) -> bytes:
    return (
        "".join(f"data: {json.dumps(item)}\n\n" for item in chunks) + "data: [DONE]\n\n"
    ).encode()


class Recorder:
    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.bodies.append(json.loads(request.content))
        return self.handler(request)


def make_provider(handler: Handler) -> tuple[OpenAIProvider, Recorder]:
    recorder = Recorder(handler)
    client = openai.AsyncOpenAI(
        api_key="k",
        max_retries=0,
        http_client=openai.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(recorder)),
    )
    return OpenAIProvider("k", client=client), recorder


def ok_handler(chunks: list[dict], headers: dict[str, str] | None = None) -> Handler:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            content=stream_body(chunks),
            headers={"content-type": "text/event-stream", **(headers or {})},
        )

    return handler


def request_for(
    model_id: str, *, temperature: float | None = None, system: str | None = "sys"
) -> GenerationRequest:
    return GenerationRequest(
        model=specs()[model_id],
        system=system,
        prompt="hi",
        temperature=temperature,
        max_tokens=64,
        thinking=False,
        timeout_s=30,
    )


async def test_request_body_and_stream_parsing() -> None:
    provider, recorder = make_provider(
        ok_handler([chunk("Hel"), chunk("lo", "stop"), USAGE_CHUNK], {"x-request-id": "req_oa"})
    )
    events = [event async for event in provider.stream(request_for("gpt-5.5"))]
    assert events[:2] == [TextDelta("Hel"), TextDelta("lo")]
    final = events[-1]
    assert isinstance(final, Completed)
    assert final.result.text == "Hello"
    assert final.result.input_tokens == 5
    assert final.result.output_tokens == 2
    assert final.result.finish_reason == "stop"
    assert final.result.request_id == "req_oa"
    assert final.result.thinking is None
    body = recorder.bodies[0]
    assert body == {
        "model": "gpt-5.5",
        "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
        "max_completion_tokens": 64,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    await provider.aclose()


async def test_temperature_is_sent_only_when_set() -> None:
    provider, recorder = make_provider(ok_handler([chunk("x", "stop"), USAGE_CHUNK]))
    await provider.generate(request_for("gpt-4.1-mini", temperature=0.3, system=None))
    body = recorder.bodies[0]
    assert body["temperature"] == 0.3
    assert body["messages"] == [{"role": "user", "content": "hi"}]


def test_temperature_support_by_prefix() -> None:
    catalog = specs()
    assert catalog["gpt-4.1-mini"].supports_temperature
    assert not catalog["gpt-5.5"].supports_temperature


@pytest.mark.parametrize(
    ("finish", "expected"),
    [("stop", "stop"), ("length", "length"), ("content_filter", "content_filter"), (None, "other")],
)
async def test_finish_reasons(finish: str | None, expected: str) -> None:
    provider, _ = make_provider(ok_handler([chunk("x", finish), USAGE_CHUNK]))
    result = await provider.generate(request_for("gpt-5.5"))
    assert result.finish_reason == expected


async def test_missing_usage_falls_back_to_heuristic_and_chunk_id() -> None:
    provider, _ = make_provider(ok_handler([chunk("abcdefgh", "stop", cid="chatcmpl-9")]))
    result = await provider.generate(request_for("gpt-5.5"))
    assert result.input_tokens == 1 + 1  # "sys" + "hi"
    assert result.output_tokens == 2
    assert result.request_id == "chatcmpl-9"


def error_handler(
    status: int, body: dict[str, Any], headers: dict[str, str] | None = None
) -> Handler:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            status, json={"error": body}, headers={"x-request-id": "req_e", **(headers or {})}
        )

    return handler


@pytest.mark.parametrize(
    ("status", "body", "kind", "param", "retry_after"),
    [
        (400, {"message": "bad", "type": "invalid_request_error", "param": "temperature"},
         ProviderErrorKind.INVALID_REQUEST, "temperature", None),
        (400, {"message": "bad", "param": "this is not an identifier!"},
         ProviderErrorKind.INVALID_REQUEST, None, None),
        (401, {"message": "no key sk-abcdefghijklmnopqrstuvwx"},
         ProviderErrorKind.AUTH, None, None),
        (403, {"message": "forbidden"}, ProviderErrorKind.AUTH, None, None),
        (404, {"message": "no model"}, ProviderErrorKind.INVALID_REQUEST, None, None),
        (409, {"message": "conflict"}, ProviderErrorKind.INVALID_REQUEST, None, None),
        (422, {"message": "bad"}, ProviderErrorKind.INVALID_REQUEST, None, None),
        (429, {"message": "slow down", "code": "rate_limit_exceeded"},
         ProviderErrorKind.RATE_LIMITED, None, 3.0),
        (429, {"message": "quota", "code": "insufficient_quota"},
         ProviderErrorKind.AUTH, None, None),
        (500, {"message": "oops"}, ProviderErrorKind.PROVIDER_ERROR, None, None),
        (503, {"message": "busy"}, ProviderErrorKind.OVERLOADED, None, 3.0),
    ],
)  # fmt: skip
async def test_error_mapping(
    status: int,
    body: dict[str, Any],
    kind: ProviderErrorKind,
    param: str | None,
    retry_after: float | None,
) -> None:
    provider, _ = make_provider(error_handler(status, body, {"retry-after": "3"}))
    with pytest.raises(ProviderError) as info:
        await provider.generate(request_for("gpt-5.5"))
    error = info.value
    assert error.kind is kind
    assert error.param == param
    assert error.retry_after == retry_after
    assert error.upstream_status == status
    assert error.provider_request_id == "req_e"
    assert "OpenAI" in error.message


async def test_connection_and_timeout_errors() -> None:
    def broken(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    def slow(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    for handler, kind in (
        (broken, ProviderErrorKind.PROVIDER_ERROR),
        (slow, ProviderErrorKind.TIMEOUT),
    ):
        provider, _ = make_provider(handler)
        with pytest.raises(ProviderError) as info:
            await provider.generate(request_for("gpt-5.5"))
        assert info.value.kind is kind


def test_unknown_sdk_error_is_provider_error() -> None:
    assert map_openai_error(openai.OpenAIError("x")).kind is ProviderErrorKind.PROVIDER_ERROR


async def test_unconfigured_and_lazy_client() -> None:
    provider = OpenAIProvider(None)
    assert not provider.is_configured()
    with pytest.raises(ProviderError):
        await provider.generate(request_for("gpt-5.5"))
    configured = OpenAIProvider("k", base_url="https://example.invalid/v1", max_retries=1)
    client = configured._get_client()
    assert str(client.base_url).startswith("https://example.invalid/v1")
    assert configured._get_client() is client
    await configured.aclose()
    assert configured._client is None
