"""Single runs: validation, provider call (plain or streamed) and history persistence."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime

import anyio

from app.db import new_id, utcnow
from app.errors import error_envelope, missing_variables, not_found, provider_app_error
from app.models import HistoryEntry, PromptVersion
from app.providers.base import (
    Completed,
    GenerationRequest,
    GenerationResult,
    ModelSpec,
    ProviderError,
    ProviderErrorKind,
    TextDelta,
    ThinkingDelta,
    log_provider_failure,
)
from app.providers.catalog import compute_cost
from app.schemas import RunParams, RunRequest, RunResult, RunStartEvent
from app.services import history, templating
from app.services.common import (
    EffectiveParams,
    call_generate,
    effective_params,
    resolve_model_id,
    single_max_tokens,
)
from app.services.validation import (
    check_max_tokens,
    check_rendered_length,
    check_template,
    check_variables,
)
from app.sse import encode_event
from app.state import AppState

logger = logging.getLogger(__name__)

INTERNAL_ERROR_MESSAGE = "An unexpected error occurred."


@dataclass(frozen=True)
class PreparedRun:
    """A validated run, ready to send to the provider."""

    spec: ModelSpec
    system_template: str | None
    prompt_template: str
    variables: dict[str, str]
    rendered_system: str | None
    rendered_prompt: str
    params: EffectiveParams
    prompt_version_id: str | None
    save_history: bool
    timeout_s: float
    source: str = "run"
    group_id: str | None = None

    def generation_request(self) -> GenerationRequest:
        return GenerationRequest(
            model=self.spec,
            system=self.rendered_system,
            prompt=self.rendered_prompt,
            temperature=self.params.temperature,
            max_tokens=self.params.max_tokens,
            thinking=self.params.thinking,
            timeout_s=self.timeout_s,
        )

    def history_entry(
        self,
        history_id: str,
        created_at: datetime,
        *,
        status: str,
        output: str = "",
        thinking: str | None = None,
        result: GenerationResult | None = None,
        latency_ms: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> HistoryEntry:
        """A history row for this run (``result`` set on success)."""
        warnings = list(self.params.warnings)
        if result is not None:
            warnings += result.warnings
        return HistoryEntry(
            id=history_id,
            created_at=created_at,
            source=self.source,
            group_id=self.group_id,
            prompt_version_id=self.prompt_version_id,
            model=self.spec.id,
            provider=self.spec.provider.value,
            status=status,
            system_template=self.system_template,
            prompt_template=self.prompt_template,
            variables=dict(self.variables),
            rendered_system=self.rendered_system,
            rendered_prompt=self.rendered_prompt,
            params=self.params.as_dict(),
            output=result.text if result is not None else output,
            thinking=result.thinking if result is not None else thinking,
            input_tokens=result.input_tokens if result is not None else None,
            output_tokens=result.output_tokens if result is not None else None,
            latency_ms=result.latency_ms if result is not None else latency_ms,
            ttft_ms=result.ttft_ms if result is not None else None,
            finish_reason=result.finish_reason if result is not None else None,
            request_id=result.request_id if result is not None else None,
            cost_usd=(
                compute_cost(self.spec.pricing, result.input_tokens, result.output_tokens)
                if result is not None
                else None
            ),
            warnings=warnings,
            error_code=error_code,
            error_message=error_message,
        )

    def run_result(
        self, history_id: str | None, created_at: datetime, result: GenerationResult
    ) -> RunResult:
        return RunResult(
            id=history_id,
            created_at=created_at,
            model=self.spec.id,
            provider=self.spec.provider.value,
            text=result.text,
            thinking=result.thinking,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=result.latency_ms,
            ttft_ms=result.ttft_ms,
            finish_reason=result.finish_reason,
            request_id=result.request_id,
            cost_usd=compute_cost(self.spec.pricing, result.input_tokens, result.output_tokens),
            warnings=[*self.params.warnings, *result.warnings],
            rendered_system=self.rendered_system,
            rendered_prompt=self.rendered_prompt,
            params=RunParams(**self.params.as_dict()),
        )


async def ensure_version_exists(state: AppState, version_id: str | None) -> None:
    """404 when a referenced prompt version does not exist."""
    if version_id is None:
        return
    async with state.db.read() as session:
        if await session.get(PromptVersion, version_id) is None:
            raise not_found("prompt_version")


async def prepare_run(state: AppState, req: RunRequest) -> PreparedRun:
    """Validate a run request and resolve the model, templates and parameters."""
    settings = state.settings
    check_template(settings, system=req.system, prompt=req.prompt)
    check_variables(settings, req.variables)
    check_max_tokens(settings, req.max_tokens)
    spec = resolve_model_id(state, req.model)
    await ensure_version_exists(state, req.prompt_version_id)
    rendered = templating.render(req.system, req.prompt, req.variables)
    if rendered.missing:
        raise missing_variables(rendered.missing)
    system = templating.normalize_system(rendered.system)
    check_rendered_length(settings, system, rendered.prompt)
    max_tokens = single_max_tokens(spec, settings, req.max_tokens)
    params = effective_params(
        spec, temperature=req.temperature, max_tokens=max_tokens, thinking=req.thinking
    )
    return PreparedRun(
        spec=spec,
        system_template=req.system,
        prompt_template=req.prompt,
        variables=dict(req.variables),
        rendered_system=system,
        rendered_prompt=rendered.prompt,
        params=params,
        prompt_version_id=req.prompt_version_id,
        save_history=req.save_history,
        timeout_s=settings.request_timeout_seconds,
    )


async def execute_run(state: AppState, prepared: PreparedRun) -> RunResult:
    """Run to completion. Provider failures are saved to history and raised as envelopes."""
    history_id = new_id() if prepared.save_history else None
    created_at = utcnow()
    started = time.monotonic()
    try:
        result = await call_generate(state, prepared.spec, prepared.generation_request())
    except ProviderError as error:
        app_error = provider_app_error(error)
        if history_id is not None:
            await history.save(
                state.db,
                prepared.history_entry(
                    history_id,
                    created_at,
                    status="error",
                    latency_ms=int((time.monotonic() - started) * 1000),
                    error_code=app_error.code,
                    error_message=app_error.message,
                ),
                state.settings.history_max_rows,
            )
            app_error = app_error.with_details(run_id=history_id)
        raise app_error from None
    if history_id is not None:
        await history.save(
            state.db,
            prepared.history_entry(history_id, created_at, status="success", result=result),
            state.settings.history_max_rows,
        )
    return prepared.run_result(history_id, created_at, result)


async def stream_run(state: AppState, prepared: PreparedRun) -> AsyncGenerator[str, None]:
    """SSE frames for a streamed run: ``start``, ``delta``..., then ``done`` or ``error``.

    The history row is written when the run ends: ``success``, ``error`` (with the partial
    output) or ``cancelled`` when the consumer stops early (client disconnect).
    """
    history_id = new_id() if prepared.save_history else None
    created_at = utcnow()
    started = time.monotonic()
    text_parts: list[str] = []
    thinking_parts: list[str] = []

    def elapsed_ms() -> int:
        return int((time.monotonic() - started) * 1000)

    async def persist(entry: HistoryEntry) -> None:
        if history_id is not None:
            await history.save(state.db, entry, state.settings.history_max_rows)

    def partial_entry(status: str, code: str | None, message: str | None) -> HistoryEntry:
        return prepared.history_entry(
            history_id or "",
            created_at,
            status=status,
            output="".join(text_parts),
            thinking="".join(thinking_parts) or None,
            latency_ms=elapsed_ms(),
            error_code=code,
            error_message=message,
        )

    start = RunStartEvent(
        run_id=history_id,
        model=prepared.spec.id,
        provider=prepared.spec.provider.value,
        created_at=created_at,
        warnings=list(prepared.params.warnings),
    )
    yield encode_event("start", start.model_dump(mode="json"))

    provider = state.registry.provider_for(prepared.spec)
    result: GenerationResult | None = None
    try:
        try:
            async with (
                asyncio.timeout(prepared.timeout_s),
                state.provider_semaphore,
                contextlib.aclosing(provider.stream(prepared.generation_request())) as events,
            ):
                async for event in events:
                    if isinstance(event, TextDelta):
                        text_parts.append(event.text)
                        yield encode_event("delta", {"type": "text", "text": event.text})
                    elif isinstance(event, ThinkingDelta):
                        thinking_parts.append(event.text)
                        yield encode_event("delta", {"type": "thinking", "text": event.text})
                    elif isinstance(event, Completed):
                        result = event.result
        except TimeoutError:
            timeout_error = ProviderError(ProviderErrorKind.TIMEOUT, prepared.spec.provider)
            log_provider_failure(logger, timeout_error, upstream_type="deadline")
            raise timeout_error from None
        if result is None:
            raise ProviderError(ProviderErrorKind.PROVIDER_ERROR, prepared.spec.provider)
    except ProviderError as error:
        app_error = provider_app_error(error)
        await persist(partial_entry("error", app_error.code, app_error.message))
        if history_id is not None:
            app_error = app_error.with_details(run_id=history_id)
        yield encode_event("error", {"error": app_error.body()})
        return
    except Exception:
        logger.exception("Streamed run failed unexpectedly")
        await persist(partial_entry("error", "internal_error", INTERNAL_ERROR_MESSAGE))
        details = {"run_id": history_id} if history_id is not None else None
        yield encode_event(
            "error", error_envelope("internal_error", INTERNAL_ERROR_MESSAGE, details)
        )
        return
    except BaseException:
        # Client disconnect (task cancelled) or the consumer closed the generator.
        with anyio.CancelScope(shield=True):
            await persist(partial_entry("cancelled", None, None))
        raise

    await persist(
        prepared.history_entry(history_id or "", created_at, status="success", result=result)
    )
    yield encode_event(
        "done", prepared.run_result(history_id, created_at, result).model_dump(mode="json")
    )
