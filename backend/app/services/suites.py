"""Test suites and their cases."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import new_id, utcnow
from app.errors import conflict, limit_exceeded, not_found
from app.models import EvalRun, TestCase, TestSuite
from app.schemas import (
    CaseInput,
    CaseOut,
    LastEval,
    SuiteCreate,
    SuiteDetail,
    SuiteSummary,
    SuiteUpdate,
)
from app.services.evaluation import normalize_assertions, validate_case_assertions
from app.services.history import contains_pattern, like_pattern
from app.services.validation import check_variables
from app.state import AppState


def case_out(case: TestCase) -> CaseOut:
    return CaseOut(
        id=case.id,
        suite_id=case.suite_id,
        name=case.name,
        variables=dict(case.variables or {}),
        assertions=list(case.assertions or []),
        position=case.position,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def check_case(state: AppState, case: CaseInput, *, case_index: int | None = None) -> None:
    loc: tuple[str | int, ...] = ("body", "variables")
    if case_index is not None:
        loc = ("body", "cases", case_index, "variables")
    check_variables(state.settings, case.variables, loc)
    validate_case_assertions(state, case.assertions, case_index=case_index)


async def _name_taken(session: AsyncSession, name: str, exclude_id: str | None = None) -> bool:
    stmt = select(TestSuite.id).where(TestSuite.name_key == name.casefold())
    if exclude_id is not None:
        stmt = stmt.where(TestSuite.id != exclude_id)
    return (await session.scalar(stmt)) is not None


async def _load_suite(session: AsyncSession, suite_id: str) -> TestSuite:
    suite = await session.get(TestSuite, suite_id)
    if suite is None:
        raise not_found("suite")
    return suite


async def _last_evals(session: AsyncSession, suite_ids: list[str]) -> dict[str, LastEval]:
    if not suite_ids:
        return {}
    newest = (
        select(EvalRun.suite_id, func.max(EvalRun.created_at).label("created_at"))
        .where(EvalRun.suite_id.in_(suite_ids))
        .group_by(EvalRun.suite_id)
        .subquery()
    )
    runs = await session.scalars(
        select(EvalRun)
        .join(
            newest,
            (EvalRun.suite_id == newest.c.suite_id) & (EvalRun.created_at == newest.c.created_at),
        )
        .order_by(EvalRun.id)
    )
    result: dict[str, LastEval] = {}
    for run in runs:
        if run.suite_id is None or run.suite_id in result:
            continue
        result[run.suite_id] = LastEval(
            id=run.id,
            status=run.status,
            pass_rate=run.passed / run.completed if run.completed else None,
            created_at=run.created_at,
        )
    return result


def _summary_fields(suite: TestSuite, case_count: int, last: LastEval | None) -> dict[str, Any]:
    return {
        "id": suite.id,
        "name": suite.name,
        "description": suite.description,
        "case_count": case_count,
        "created_at": suite.created_at,
        "updated_at": suite.updated_at,
        "last_eval": last,
    }


async def get_suite(state: AppState, suite_id: str) -> SuiteDetail:
    async with state.db.read() as session:
        suite = await _load_suite(session, suite_id)
        cases = list(
            await session.scalars(
                select(TestCase).where(TestCase.suite_id == suite_id).order_by(TestCase.position)
            )
        )
        last = (await _last_evals(session, [suite_id])).get(suite_id)
    return SuiteDetail(
        **_summary_fields(suite, len(cases), last), cases=[case_out(case) for case in cases]
    )


async def list_suites(
    state: AppState, *, q: str | None, limit: int, offset: int
) -> tuple[list[SuiteSummary], int]:
    filters: list[Any] = []
    if q:
        pattern = like_pattern(q)
        filters.append(
            or_(
                contains_pattern(TestSuite.name, pattern),
                contains_pattern(TestSuite.description, pattern),
            )
        )
    case_count = (
        select(func.count(TestCase.id))
        .where(TestCase.suite_id == TestSuite.id)
        .correlate(TestSuite)
        .scalar_subquery()
    )
    async with state.db.read() as session:
        total = await session.scalar(select(func.count(TestSuite.id)).where(*filters))
        rows = (
            await session.execute(
                select(TestSuite, case_count)
                .where(*filters)
                .order_by(TestSuite.updated_at.desc(), TestSuite.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
        last = await _last_evals(session, [suite.id for suite, _count in rows])
    items = [
        SuiteSummary(**_summary_fields(suite, int(count), last.get(suite.id)))
        for suite, count in rows
    ]
    return items, int(total or 0)


async def create_suite(state: AppState, req: SuiteCreate) -> SuiteDetail:
    if len(req.cases) > state.settings.max_cases_per_suite:
        raise limit_exceeded("max_cases_per_suite", state.settings.max_cases_per_suite)
    for index, case in enumerate(req.cases):
        check_case(state, case, case_index=index)
    suite_id = new_id()
    async with state.db.write() as session:
        if await _name_taken(session, req.name):
            raise conflict()
        now = utcnow()
        session.add(
            TestSuite(
                id=suite_id,
                name=req.name,
                name_key=req.name.casefold(),
                description=req.description,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        for position, case in enumerate(req.cases):
            session.add(
                TestCase(
                    suite_id=suite_id,
                    name=case.name,
                    variables=dict(case.variables),
                    assertions=normalize_assertions(case.assertions),
                    position=position,
                    created_at=now,
                    updated_at=now,
                )
            )
    return await get_suite(state, suite_id)


async def update_suite(state: AppState, suite_id: str, req: SuiteUpdate) -> SuiteDetail:
    async with state.db.write() as session:
        suite = await _load_suite(session, suite_id)
        if req.name is not None and req.name != suite.name:
            if await _name_taken(session, req.name, exclude_id=suite_id):
                raise conflict()
            suite.name = req.name
            suite.name_key = req.name.casefold()
        if req.description is not None:
            suite.description = req.description
        suite.updated_at = utcnow()
    return await get_suite(state, suite_id)


async def delete_suite(state: AppState, suite_id: str) -> None:
    async with state.db.write() as session:
        await session.delete(await _load_suite(session, suite_id))


async def add_case(state: AppState, suite_id: str, req: CaseInput) -> CaseOut:
    check_case(state, req)
    async with state.db.write() as session:
        suite = await _load_suite(session, suite_id)
        count = await session.scalar(
            select(func.count(TestCase.id)).where(TestCase.suite_id == suite_id)
        )
        if int(count or 0) >= state.settings.max_cases_per_suite:
            raise limit_exceeded("max_cases_per_suite", state.settings.max_cases_per_suite)
        top = await session.scalar(
            select(func.max(TestCase.position)).where(TestCase.suite_id == suite_id)
        )
        now = utcnow()
        case = TestCase(
            id=new_id(),
            suite_id=suite_id,
            name=req.name,
            variables=dict(req.variables),
            assertions=normalize_assertions(req.assertions),
            position=(top + 1) if top is not None else 0,
            created_at=now,
            updated_at=now,
        )
        session.add(case)
        suite.updated_at = now
    return case_out(case)


async def _load_case(session: AsyncSession, suite_id: str, case_id: str) -> TestCase:
    case = await session.get(TestCase, case_id)
    if case is None or case.suite_id != suite_id:
        raise not_found("case")
    return case


async def update_case(state: AppState, suite_id: str, case_id: str, req: CaseInput) -> CaseOut:
    check_case(state, req)
    async with state.db.write() as session:
        suite = await _load_suite(session, suite_id)
        case = await _load_case(session, suite_id, case_id)
        now = utcnow()
        case.name = req.name
        case.variables = dict(req.variables)
        case.assertions = normalize_assertions(req.assertions)
        case.updated_at = now
        suite.updated_at = now
    return case_out(case)


async def delete_case(state: AppState, suite_id: str, case_id: str) -> None:
    async with state.db.write() as session:
        suite = await _load_suite(session, suite_id)
        await session.delete(await _load_case(session, suite_id, case_id))
        suite.updated_at = utcnow()
