"""Scripted fake provider and helpers for router and service tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from app.providers.base import (
    Completed,
    FinishReason,
    GenerationRequest,
    GenerationResult,
    Provider,
    ProviderError,
    ProviderName,
    StreamEvent,
    TextDelta,
    ThinkingDelta,
)


@dataclass
class Script:
    """What a :class:`ScriptedProvider` does for one call."""

    text: str = "Hello from the fake provider."
    thinking: str | None = None
    chunks: list[str] | None = None
    error: ProviderError | None = None
    error_after_chunks: int | None = None
    delay: float = 0.0
    input_tokens: int = 12
    output_tokens: int = 7
    finish_reason: FinishReason = "stop"
    request_id: str | None = "req_fake"
    warnings: list[str] = field(default_factory=list)
    latency_ms: int = 42
    ttft_ms: int | None = 7

    def pieces(self) -> list[str]:
        if self.chunks is not None:
            return self.chunks
        words = self.text.split(" ")
        return [word + (" " if i < len(words) - 1 else "") for i, word in enumerate(words)]


ScriptFn = Callable[[GenerationRequest], Script]


class ScriptedProvider(Provider):
    """A provider whose behaviour is configured per test (no network)."""

    def __init__(
        self,
        name: ProviderName,
        script: Script | ScriptFn | None = None,
        *,
        configured: bool = True,
        count: int | None = None,
        count_error: Exception | None = None,
    ) -> None:
        self.name = name
        self._script = script or Script()
        self._configured = configured
        self._count = count
        self._count_error = count_error
        self.calls: list[GenerationRequest] = []
        self.count_calls: list[GenerationRequest] = []
        self.closed = False

    def script_for(self, req: GenerationRequest) -> Script:
        return self._script(req) if callable(self._script) else self._script

    def is_configured(self) -> bool:
        return self._configured

    async def stream(self, req: GenerationRequest) -> AsyncIterator[StreamEvent]:
        self.calls.append(req)
        script = self.script_for(req)
        if script.delay:
            await asyncio.sleep(script.delay)
        if script.error is not None and script.error_after_chunks is None:
            raise script.error
        if script.thinking:
            yield ThinkingDelta(script.thinking)
        for index, piece in enumerate(script.pieces()):
            if script.error is not None and index == script.error_after_chunks:
                raise script.error
            yield TextDelta(piece)
        if script.error is not None:
            raise script.error
        yield Completed(
            GenerationResult(
                text="".join(script.pieces()),
                thinking=script.thinking,
                input_tokens=script.input_tokens,
                output_tokens=script.output_tokens,
                latency_ms=script.latency_ms,
                ttft_ms=script.ttft_ms,
                finish_reason=script.finish_reason,
                request_id=script.request_id,
                warnings=list(script.warnings),
            )
        )

    async def count_tokens(self, req: GenerationRequest) -> int | None:
        self.count_calls.append(req)
        if self._count_error is not None:
            raise self._count_error
        return self._count

    async def aclose(self) -> None:
        self.closed = True


def parse_sse(body: str) -> list[tuple[str, object]]:
    """Parse an SSE body into ``(event, data)`` pairs; comment frames become ``(":", text)``."""
    events: list[tuple[str, object]] = []
    for frame in body.replace("\r\n", "\n").split("\n\n"):
        if not frame.strip():
            continue
        if frame.startswith(":"):
            events.append((":", frame[1:].strip()))
            continue
        name = "message"
        data_lines: list[str] = []
        for line in frame.split("\n"):
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        events.append((name, json.loads("\n".join(data_lines))))
    return events
