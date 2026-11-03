"""Comparisons: every variant on every selected model, concurrently, with partial failures."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import string
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime

import anyio

from app.db import new_id, utcnow
from app.errors import (
    error_body,
    error_envelope,
    invalid_parameter,
    limit_exceeded,
    missing_variables,
    provider_app_error,
)
from app.models import HistoryEntry
from app.providers.base import ModelSpec, ProviderError
from app.schemas import (
    CompareCell,
    CompareCellRef,
    CompareRequest,
    CompareResult,
    CompareStartEvent,
    CompareSummary,
    CompareVariant,
    ErrorBody,
    RunParams,
    RunResult,
)
from app.services import history, templating
from app.services.common import (
    call_generate,
    effective_params,
    resolve_max_tokens,
    resolve_models,
)
from app.services.runner import PreparedRun, ensure_version_exists
from app.services.validation import (
    check_max_tokens,
    check_rendered_length,
    check_template,
    check_variables,
)
from app.sse import encode_event
from app.state import AppState

logger = logging.getLogger(__name__)

DEADLINE_MESSAGE = "The comparison deadline was reached before this cell finished."
INTERNAL_ERROR_MESSAGE = "An unexpected error occurred."


def variant_label(index: int) -> str:
    """``Variant A``, ``Variant B``, ... (then ``Variant 27`` and so on past Z)."""
    letters = string.ascii_uppercase
    return f"Variant {letters[index]}" if index < len(letters) else f"Variant {index + 1}"


@dataclass(frozen=True)
class CellPlan:
    ref: CompareCellRef
    variant_label: str
    run: PreparedRun


@dataclass
class PreparedCompare:
    id: str
    created_at: datetime
    variants: list[CompareVariant]
    models: list[ModelSpec]
    variables: dict[str, str]
    params: RunParams
    cells: list[CellPlan]
    warnings: list[str]
    total_timeout_s: float
    save_history: bool


async def prepare_compare(state: AppState, req: CompareRequest) -> PreparedCompare:
    """Validate everything before any provider call."""
    settings = state.settings
    if len(req.variants) > settings.max_compare_variants:
        raise limit_exceeded("max_compare_variants", settings.max_compare_variants)
    if len(req.models) > settings.max_compare_models:
        raise limit_exceeded("max_compare_models", settings.max_compare_models)
    for index, variant in enumerate(req.variants):
        check_template(
            settings, system=variant.system, prompt=variant.prompt, loc=("body", "variants", index)
        )
    check_variables(settings, req.variables)
    check_max_tokens(settings, req.max_tokens)
    specs = resolve_models(state, req.models)
    cell_count = len(req.variants) * len(specs)
    if cell_count > settings.max_compare_cells:
        raise limit_exceeded("max_compare_cells", settings.max_compare_cells)
    for variant in req.variants:
        await ensure_version_exists(state, variant.prompt_version_id)

    rendered_variants = [
        templating.render(variant.system, variant.prompt, req.variables) for variant in req.variants
    ]
    if any(rendered.missing for rendered in rendered_variants):
        union = sorted({name for rendered in rendered_variants for name in rendered.missing})
        raise missing_variables(
            union, by_variant=[list(rendered.missing) for rendered in rendered_variants]
        )
    systems = [templating.normalize_system(rendered.system) for rendered in rendered_variants]
    for system, rendered in zip(systems, rendered_variants, strict=True):
        check_rendered_length(settings, system, rendered.prompt)

    max_tokens = resolve_max_tokens(specs, settings, req.max_tokens)
    timeout_s = settings.request_timeout_seconds
    if req.timeout_seconds is not None:
        if not 1 <= req.timeout_seconds <= settings.request_timeout_seconds:
            raise invalid_parameter(
                "timeout_seconds",
                f"timeout_seconds must be between 1 and {settings.request_timeout_seconds}.",
                settings.request_timeout_seconds,
            )
        timeout_s = req.timeout_seconds

    comparison_id = new_id()
    variants = [
        CompareVariant(
            index=index,
            label=variant.label or variant_label(index),
            system=variant.system,
            prompt=variant.prompt,
            prompt_version_id=variant.prompt_version_id,
        )
        for index, variant in enumerate(req.variants)
    ]
    per_model = {
        spec.id: effective_params(
            spec, temperature=req.temperature, max_tokens=max_tokens, thinking=req.thinking
        )
        for spec in specs
    }
    warnings: list[str] = []
    for spec in specs:
        for warning in per_model[spec.id].warnings:
            if warning not in warnings:
                warnings.append(warning)

    cells: list[CellPlan] = []
    for v_index, variant in enumerate(variants):
        for m_index, spec in enumerate(specs):
            cells.append(
                CellPlan(
                    ref=CompareCellRef(
                        index=v_index * len(specs) + m_index,
                        variant_index=v_index,
                        model=spec.id,
                        provider=spec.provider.value,
                    ),
                    variant_label=variant.label,
                    run=PreparedRun(
                        spec=spec,
                        system_template=variant.system,
                        prompt_template=variant.prompt,
                        variables=dict(req.variables),
                        rendered_system=systems[v_index],
                        rendered_prompt=rendered_variants[v_index].prompt,
                        params=per_model[spec.id],
                        prompt_version_id=variant.prompt_version_id,
                        save_history=req.save_history,
                        timeout_s=timeout_s,
                        source="compare",
                        group_id=comparison_id,
                    ),
                )
            )
    return PreparedCompare(
        id=comparison_id,
        created_at=utcnow(),
        variants=variants,
        models=specs,
        variables=dict(req.variables),
        params=RunParams(temperature=req.temperature, max_tokens=max_tokens, thinking=req.thinking),
        cells=cells,
        warnings=warnings,
        total_timeout_s=settings.compare_total_timeout_seconds,
        save_history=req.save_history,
    )


@dataclass
class _Finished:
    cell: CompareCell
    entry: HistoryEntry | None


@dataclass
class CompareExecution:
    """Runs the cells of a prepared comparison and reports them in completion order."""

    state: AppState
    prepared: PreparedCompare
    finished: dict[int, CompareCell] = field(default_factory=dict)
    _queue: asyncio.Queue[_Finished] = field(default_factory=asyncio.Queue)
    _tasks: dict[int, asyncio.Task[None]] = field(default_factory=dict)

    def _cell(
        self, plan: CellPlan, *, result: RunResult | None = None, error: ErrorBody | None = None
    ) -> CompareCell:
        return CompareCell(
            **plan.ref.model_dump(),
            variant_label=plan.variant_label,
            status="ok" if error is None else "error",
            result=result,
            error=error,
        )

    def _error(
        self,
        plan: CellPlan,
        code: str,
        message: str,
        details: dict[str, object],
        created_at: datetime,
        latency_ms: int | None,
    ) -> _Finished:
        history_id = new_id() if self.prepared.save_history else None
        if history_id is not None:
            details = {**details, "run_id": history_id}
        entry = (
            plan.run.history_entry(
                history_id,
                created_at,
                status="error",
                latency_ms=latency_ms,
                error_code=code,
                error_message=message,
            )
            if history_id is not None
            else None
        )
        body = ErrorBody(**error_body(code, message, details))
        return _Finished(self._cell(plan, error=body), entry)

    async def _run_cell(self, plan: CellPlan, semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            created_at = utcnow()
            started = time.monotonic()
            try:
                result = await call_generate(
                    self.state, plan.run.spec, plan.run.generation_request()
                )
            except ProviderError as error:
                app_error = provider_app_error(error)
                finished = self._error(
                    plan,
                    app_error.code,
                    app_error.message,
                    app_error.details or {},
                    created_at,
                    int((time.monotonic() - started) * 1000),
                )
            except Exception:
                logger.exception("Comparison cell %s failed unexpectedly", plan.ref.index)
                finished = self._error(
                    plan,
                    "internal_error",
                    INTERNAL_ERROR_MESSAGE,
                    {},
                    created_at,
                    int((time.monotonic() - started) * 1000),
                )
            else:
                history_id = new_id() if self.prepared.save_history else None
                entry = (
                    plan.run.history_entry(history_id, created_at, status="success", result=result)
                    if history_id is not None
                    else None
                )
                run_result = plan.run.run_result(history_id, created_at, result)
                finished = _Finished(self._cell(plan, result=run_result), entry)
        self._queue.put_nowait(finished)

    async def _record(self, finished: _Finished) -> CompareCell:
        if finished.entry is not None:
            await history.save(self.state.db, finished.entry, self.state.settings.history_max_rows)
        self.finished[finished.cell.index] = finished.cell
        return finished.cell

    async def _cancel_outstanding(self) -> None:
        pending = [task for task in self._tasks.values() if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            with anyio.CancelScope(shield=True):
                await asyncio.gather(*pending, return_exceptions=True)

    async def cells(self) -> AsyncGenerator[CompareCell, None]:
        """Start every cell and yield each one as it finishes (history written first).

        Cells still running at the overall deadline are cancelled and reported as
        ``provider_timeout`` errors. Closing the generator early cancels outstanding cells,
        which are then not written to history.
        """
        semaphore = asyncio.Semaphore(self.state.settings.compare_concurrency)
        for plan in self.prepared.cells:
            self._tasks[plan.ref.index] = asyncio.create_task(self._run_cell(plan, semaphore))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.prepared.total_timeout_s
        total = len(self.prepared.cells)
        try:
            while len(self.finished) < total:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    finished = await asyncio.wait_for(self._queue.get(), timeout=remaining)
                except TimeoutError:
                    break
                yield await self._record(finished)
            if len(self.finished) < total:
                await self._cancel_outstanding()
                while not self._queue.empty():
                    yield await self._record(self._queue.get_nowait())
                for plan in self.prepared.cells:
                    if plan.ref.index in self.finished:
                        continue
                    timed_out = self._error(
                        plan,
                        "provider_timeout",
                        DEADLINE_MESSAGE,
                        {"provider": plan.run.spec.provider.value},
                        utcnow(),
                        None,
                    )
                    yield await self._record(timed_out)
        finally:
            await self._cancel_outstanding()

    def result(self) -> CompareResult:
        cells = [self.finished[index] for index in sorted(self.finished)]
        ok = [(cell.index, cell.result) for cell in cells if cell.result is not None]
        fastest = min(ok, key=lambda pair: (pair[1].latency_ms, pair[0]), default=None)
        priced = [(index, res.cost_usd) for index, res in ok if res.cost_usd is not None]
        cheapest = min(priced, key=lambda pair: (pair[1], pair[0]), default=None)
        prepared = self.prepared
        return CompareResult(
            id=prepared.id,
            created_at=prepared.created_at,
            variants=prepared.variants,
            models=[spec.id for spec in prepared.models],
            variables=prepared.variables,
            params=prepared.params,
            cells=cells,
            summary=CompareSummary(
                ok_count=len(ok),
                error_count=len(cells) - len(ok),
                fastest_cell=fastest[0] if fastest else None,
                cheapest_cell=cheapest[0] if cheapest else None,
            ),
            warnings=list(prepared.warnings),
        )


async def run_compare(state: AppState, prepared: PreparedCompare) -> CompareResult:
    """Run all cells and return the full result (HTTP 200 even when some cells failed)."""
    execution = CompareExecution(state, prepared)
    async with contextlib.aclosing(execution.cells()) as cells:
        async for _cell in cells:
            pass
    return execution.result()


async def stream_compare(state: AppState, prepared: PreparedCompare) -> AsyncGenerator[str, None]:
    """SSE frames: ``start``, one ``cell`` per finished cell, then ``done``."""
    start = CompareStartEvent(
        comparison_id=prepared.id,
        created_at=prepared.created_at,
        cells=[plan.ref for plan in prepared.cells],
        warnings=list(prepared.warnings),
    )
    yield encode_event("start", start.model_dump(mode="json"))
    execution = CompareExecution(state, prepared)
    try:
        async with contextlib.aclosing(execution.cells()) as cells:
            async for cell in cells:
                yield encode_event("cell", cell.model_dump(mode="json"))
        result = execution.result()
    except Exception:
        logger.exception("Streamed comparison failed unexpectedly")
        yield encode_event("error", error_envelope("internal_error", INTERNAL_ERROR_MESSAGE))
        return
    yield encode_event("done", result.model_dump(mode="json"))
