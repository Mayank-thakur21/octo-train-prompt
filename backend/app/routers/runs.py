"""Runs (plain and streamed) and token estimates."""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import AuthFirstRoute, StateDep, guard
from app.schemas import RunRequest, RunResult, TokenEstimate, TokenEstimateRequest
from app.services import runner, tokens
from app.sse import EventStreamResponse, with_keepalive

router = APIRouter(prefix="/api", route_class=AuthFirstRoute, tags=["runs"])


@router.post("/runs", response_model=RunResult, dependencies=[guard("runs")])
async def create_run(body: RunRequest, state: StateDep) -> RunResult:
    """Render the templates and run them on one model."""
    prepared = await runner.prepare_run(state, body)
    return await runner.execute_run(state, prepared)


@router.post(
    "/runs/stream",
    response_class=EventStreamResponse,
    dependencies=[guard("runs")],
    responses={200: {"content": {"text/event-stream": {}}, "description": "SSE stream"}},
)
async def stream_run(body: RunRequest, state: StateDep) -> EventStreamResponse:
    """Like ``POST /api/runs`` but streams ``start``, ``delta``, ``done``/``error`` events."""
    prepared = await runner.prepare_run(state, body)
    frames = runner.stream_run(state, prepared)
    return EventStreamResponse(with_keepalive(frames, state.settings.sse_keepalive_seconds))


@router.post("/tokens/estimate", response_model=TokenEstimate, dependencies=[guard("tokens")])
async def estimate_tokens(body: TokenEstimateRequest, state: StateDep) -> TokenEstimate:
    """Input token estimate for a rendered prompt (exact for configured Anthropic models)."""
    return await tokens.estimate_tokens_for(state, body)
