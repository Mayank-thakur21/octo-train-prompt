"""Server-Sent Events: frame encoding, keepalive pings and a disconnect-aware response."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

import anyio
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from app.errors import error_envelope

logger = logging.getLogger(__name__)

PING_FRAME = ": ping\n\n"

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}


def encode_event(event: str, payload: Any) -> str:
    """One SSE frame with a single-line JSON ``data`` field."""
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n"


class _End:
    """Queue sentinel marking the end of the source stream."""


async def with_keepalive(source: AsyncGenerator[str, None], interval: float) -> AsyncIterator[str]:
    """Forward frames from ``source`` and emit a ping comment after ``interval`` idle seconds.

    ``source`` runs in its own task, so it can use ``asyncio.timeout`` freely. When the consumer
    stops early (client disconnect), that task is cancelled and awaited so the source's cleanup
    (for example saving a cancelled history row) completes.
    """
    queue: asyncio.Queue[str | _End | BaseException] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for frame in source:
                queue.put_nowait(frame)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # surfaced to the consumer
            queue.put_nowait(exc)
        finally:
            await source.aclose()
        queue.put_nowait(_End())

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval)
            except TimeoutError:
                yield PING_FRAME
                continue
            if isinstance(item, _End):
                break
            if isinstance(item, BaseException):
                logger.error("Event stream failed", exc_info=item)
                yield encode_event(
                    "error",
                    error_envelope("internal_error", "An unexpected error occurred."),
                )
                break
            yield item
    finally:
        if not task.done():
            task.cancel()
        with anyio.CancelScope(shield=True):
            await asyncio.gather(task, return_exceptions=True)


class EventStreamResponse(StreamingResponse):
    """``text/event-stream`` response that cancels the stream when the client disconnects.

    Unlike the base class, it always listens for ``http.disconnect`` (whatever ASGI spec
    version the server reports), so an aborted fetch stops provider work promptly.
    """

    media_type = "text/event-stream"

    def __init__(
        self,
        content: AsyncIterator[str],
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            content, status_code=status_code, headers={**SSE_HEADERS, **(headers or {})}
        )
        self.headers["content-type"] = "text/event-stream; charset=utf-8"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async with anyio.create_task_group() as task_group:

            async def run_stream() -> None:
                try:
                    await self.stream_response(send)
                except OSError:
                    logger.info("SSE client went away while sending")
                finally:
                    task_group.cancel_scope.cancel()

            task_group.start_soon(run_stream)
            await self.listen_for_disconnect(receive)
            task_group.cancel_scope.cancel()
