"""Test suites and cases."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.deps import AuthFirstRoute, StateDep, guard
from app.routers.params import Limit, Offset
from app.schemas import CaseInput, CaseOut, SuiteCreate, SuiteDetail, SuitePage, SuiteUpdate
from app.services import suites
from app.services.validation import parse_id

router = APIRouter(
    prefix="/api", route_class=AuthFirstRoute, tags=["suites"], dependencies=[guard("default")]
)


@router.get("/suites", response_model=SuitePage)
async def list_suites(
    state: StateDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> SuitePage:
    """Suites, most recently updated first."""
    items, total = await suites.list_suites(state, q=q, limit=limit, offset=offset)
    return SuitePage(items=items, total=total, limit=limit, offset=offset)


@router.post("/suites", response_model=SuiteDetail, status_code=201)
async def create_suite(body: SuiteCreate, state: StateDep) -> SuiteDetail:
    return await suites.create_suite(state, body)


@router.get("/suites/{suite_id}", response_model=SuiteDetail)
async def get_suite(suite_id: str, state: StateDep) -> SuiteDetail:
    return await suites.get_suite(state, parse_id(suite_id, "suite"))


@router.patch("/suites/{suite_id}", response_model=SuiteDetail)
async def update_suite(suite_id: str, body: SuiteUpdate, state: StateDep) -> SuiteDetail:
    return await suites.update_suite(state, parse_id(suite_id, "suite"), body)


@router.delete("/suites/{suite_id}", status_code=204, response_class=Response)
async def delete_suite(suite_id: str, state: StateDep) -> Response:
    await suites.delete_suite(state, parse_id(suite_id, "suite"))
    return Response(status_code=204)


@router.post("/suites/{suite_id}/cases", response_model=CaseOut, status_code=201)
async def add_case(suite_id: str, body: CaseInput, state: StateDep) -> CaseOut:
    """Append a case to the suite."""
    return await suites.add_case(state, parse_id(suite_id, "suite"), body)


@router.put("/suites/{suite_id}/cases/{case_id}", response_model=CaseOut)
async def update_case(suite_id: str, case_id: str, body: CaseInput, state: StateDep) -> CaseOut:
    return await suites.update_case(
        state, parse_id(suite_id, "suite"), parse_id(case_id, "case"), body
    )


@router.delete("/suites/{suite_id}/cases/{case_id}", status_code=204, response_class=Response)
async def delete_case(suite_id: str, case_id: str, state: StateDep) -> Response:
    await suites.delete_case(state, parse_id(suite_id, "suite"), parse_id(case_id, "case"))
    return Response(status_code=204)
