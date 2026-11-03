"""Comparisons of prompt variants across models."""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import AuthFirstRoute, StateDep, guard
from app.schemas import CompareRequest, CompareResult
from app.services import compare
from app.sse import EventStreamResponse, with_keepalive

router = APIRouter(
    prefix="/api", route_class=AuthFirstRoute, tags=["compare"], dependencies=[guard("compare")]
)


@router.post("/compare", response_model=CompareResult)
async def run_compare(body: CompareRequest, state: StateDep) -> CompareResult:
    """Run every variant on every model; cell failures do not fail the request."""
    prepared = await compare.prepare_compare(state, body)
    return await compare.run_compare(state, prepared)


@router.post(
    "/compare/stream",
    response_class=EventStreamResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "SSE stream"}},
)
async def stream_compare(body: CompareRequest, state: StateDep) -> EventStreamResponse:
    """Like ``POST /api/compare`` but streams ``start``, ``cell``... and ``done`` events."""
    prepared = await compare.prepare_compare(state, body)
    frames = compare.stream_compare(state, prepared)
    return EventStreamResponse(with_keepalive(frames, state.settings.sse_keepalive_seconds))
