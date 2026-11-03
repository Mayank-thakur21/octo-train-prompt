"""SSE framing, keepalive helper and disconnect handling of the event-stream response."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from app.sse import PING_FRAME, EventStreamResponse, encode_event, with_keepalive
from tests.fakes import parse_sse


def test_encode_event_is_single_line_utf8() -> None:
    frame = encode_event("delta", {"text": "héllo\nworld"})
    assert frame == 'event: delta\ndata: {"text":"héllo\\nworld"}\n\n'


async def collect(stream) -> list[str]:
    return [frame async for frame in stream]


async def test_keepalive_pings_while_idle() -> None:
    async def slow() -> AsyncGenerator[str, None]:
        yield encode_event("start", {})
        await asyncio.sleep(0.12)
        yield encode_event("done", {})

    frames = await collect(with_keepalive(slow(), 0.03))
    assert frames[0].startswith("event: start")
    assert frames[-1].startswith("event: done")
    assert PING_FRAME in frames


async def test_keepalive_turns_source_errors_into_error_event() -> None:
    async def broken() -> AsyncGenerator[str, None]:
        yield encode_event("start", {})
        raise RuntimeError("boom")

    frames = await collect(with_keepalive(broken(), 1))
    events = parse_sse("".join(frames))
    assert events[-1] == (
        "error",
        {"error": {"code": "internal_error", "message": "An unexpected error occurred."}},
    )


async def test_keepalive_close_runs_source_cleanup() -> None:
    cleaned = asyncio.Event()

    async def endless() -> AsyncGenerator[str, None]:
        try:
            yield encode_event("start", {})
            await asyncio.sleep(60)
            yield encode_event("never", {})
        finally:
            cleaned.set()

    stream = with_keepalive(endless(), 10)
    assert (await anext(stream)).startswith("event: start")
    await stream.aclose()
    assert cleaned.is_set()


async def test_response_stops_streaming_on_disconnect() -> None:
    cancelled = asyncio.Event()

    async def endless() -> AsyncGenerator[str, None]:
        try:
            yield encode_event("start", {})
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    sent: list[dict] = []
    disconnect = asyncio.Event()

    async def receive() -> dict:
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        sent.append(message)
        if message.get("body", b"").startswith(b"event: start"):
            disconnect.set()

    response = EventStreamResponse(with_keepalive(endless(), 10))
    await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
    assert sent[0]["type"] == "http.response.start"
    headers = dict(sent[0]["headers"])
    assert headers[b"content-type"] == b"text/event-stream; charset=utf-8"
    assert headers[b"cache-control"] == b"no-cache, no-transform"
    assert cancelled.is_set()


async def test_response_handles_send_failures() -> None:
    async def frames() -> AsyncGenerator[str, None]:
        yield encode_event("start", {})

    async def receive() -> dict:
        await asyncio.sleep(60)
        return {"type": "http.disconnect"}

    async def send(_message: dict) -> None:
        raise OSError("client went away")

    response = EventStreamResponse(frames())
    await response({"type": "http"}, receive, send)
