"""Run history."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response

from app.deps import AuthFirstRoute, StateDep, guard
from app.routers.params import Limit, Offset
from app.schemas import DeletedCount, HistoryDetail, HistoryPage, HistoryStatus, ProviderId
from app.services import history
from app.services.validation import parse_id

router = APIRouter(
    prefix="/api", route_class=AuthFirstRoute, tags=["history"], dependencies=[guard("default")]
)


@router.get("/history", response_model=HistoryPage)
async def list_history(
    state: StateDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    model: Annotated[str | None, Query(max_length=128)] = None,
    provider: ProviderId | None = None,
    status: HistoryStatus | None = None,
    source: Literal["run", "compare"] | None = None,
    group_id: Annotated[str | None, Query(max_length=64)] = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> HistoryPage:
    """History entries, newest first."""
    rows, total = await history.list_history(
        state.db,
        q=q,
        model=model,
        provider=provider,
        status=status,
        source=source,
        group_id=group_id,
        limit=limit,
        offset=offset,
    )
    return HistoryPage(
        items=[history.to_summary(row) for row in rows], total=total, limit=limit, offset=offset
    )


@router.delete("/history", response_model=DeletedCount)
async def clear_history(state: StateDep) -> DeletedCount:
    """Delete every history entry."""
    return DeletedCount(deleted=await history.clear_history(state.db))


@router.get("/history/{history_id}", response_model=HistoryDetail)
async def get_history(history_id: str, state: StateDep) -> HistoryDetail:
    row = await history.get_history(state.db, parse_id(history_id, "history"))
    return history.to_detail(row)


@router.delete("/history/{history_id}", status_code=204, response_class=Response)
async def delete_history(history_id: str, state: StateDep) -> Response:
    await history.delete_history(state.db, parse_id(history_id, "history"))
    return Response(status_code=204)
