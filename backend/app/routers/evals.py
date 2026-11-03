"""Evaluation runs."""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.deps import AuthFirstRoute, StateDep, guard
from app.routers.params import Limit, Offset
from app.schemas import EvalCreate, EvalPage, EvalRunDetail, EvalRunSummary, EvalStatus
from app.services import evaluation
from app.services.validation import parse_id

router = APIRouter(prefix="/api", route_class=AuthFirstRoute, tags=["evals"])


@router.post("/evals", response_model=EvalRunDetail, status_code=202, dependencies=[guard("evals")])
async def create_eval(body: EvalCreate, state: StateDep) -> EvalRunDetail:
    """Validate and start an evaluation in the background (status ``queued``)."""
    run_id = await evaluation.create_eval(state, body)
    # The response is built before the background task starts, so it shows the run exactly as
    # accepted: queued, with every result pending.
    detail = await evaluation.run_detail(state, run_id)
    evaluation.start_eval(state, run_id)
    return detail


@router.get("/evals", response_model=EvalPage, dependencies=[guard("default")])
async def list_evals(
    state: StateDep,
    suite_id: str | None = None,
    prompt_id: str | None = None,
    status: EvalStatus | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> EvalPage:
    """Evaluation runs, newest first."""
    runs, total = await evaluation.list_runs(
        state, suite_id=suite_id, prompt_id=prompt_id, status=status, limit=limit, offset=offset
    )
    return EvalPage(
        items=[evaluation.run_summary(run) for run in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/evals/{eval_id}", response_model=EvalRunDetail, dependencies=[guard("default")])
async def get_eval(eval_id: str, state: StateDep) -> EvalRunDetail:
    return await evaluation.run_detail(state, parse_id(eval_id, "eval"))


@router.post(
    "/evals/{eval_id}/cancel", response_model=EvalRunSummary, dependencies=[guard("default")]
)
async def cancel_eval(eval_id: str, state: StateDep) -> EvalRunSummary:
    """Stop a queued or running evaluation; finished results are kept."""
    run = await evaluation.cancel_eval(state, parse_id(eval_id, "eval"))
    return evaluation.run_summary(run)


@router.delete(
    "/evals/{eval_id}",
    status_code=204,
    response_class=Response,
    dependencies=[guard("default")],
)
async def delete_eval(eval_id: str, state: StateDep) -> Response:
    """Delete an evaluation and its results (cancelling it first if it is running)."""
    await evaluation.delete_eval(state, parse_id(eval_id, "eval"))
    return Response(status_code=204)
