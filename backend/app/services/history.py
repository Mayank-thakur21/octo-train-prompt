"""Run history: persistence, retention, queries and response conversion."""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Database
from app.errors import not_found
from app.models import HistoryEntry, PromptVersion
from app.schemas import HistoryDetail, HistorySummary, RunParams

PREVIEW_CHARS = 200


def like_pattern(query: str) -> str:
    """A ``LIKE`` pattern for a case-insensitive substring search (``\\`` is the escape).

    Use it with :func:`contains_pattern`, which folds the column the same way.
    """
    escaped = query.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def contains_pattern(column: ColumnElement[Any], pattern: str) -> ColumnElement[bool]:
    """``casefold(column) LIKE pattern``; ``casefold`` is registered on every connection."""
    return func.casefold(column).like(pattern, escape="\\")


async def prune(session: AsyncSession, max_rows: int) -> None:
    """Delete rows beyond ``max_rows``, oldest first."""
    stale = (
        select(HistoryEntry.id)
        .order_by(HistoryEntry.created_at.desc(), HistoryEntry.id.desc())
        .offset(max_rows)
    )
    await session.execute(
        delete(HistoryEntry)
        .where(HistoryEntry.id.in_(stale))
        .execution_options(synchronize_session=False)
    )


async def save(db: Database, entry: HistoryEntry, max_rows: int) -> None:
    """Insert one row and apply the retention limit.

    The linked prompt version was checked before the provider call, but its prompt may have
    been deleted while the call ran. Writes are serialized, so checking again here cannot race:
    a vanished version is unlinked (as ``ON DELETE SET NULL`` would have done) instead of
    failing the insert and losing a finished, billed result.
    """
    async with db.write() as session:
        if (
            entry.prompt_version_id is not None
            and await session.get(PromptVersion, entry.prompt_version_id) is None
        ):
            entry.prompt_version_id = None
        session.add(entry)
        await session.flush()
        await prune(session, max_rows)


def to_summary(row: HistoryEntry) -> HistorySummary:
    return HistorySummary(**_summary_fields(row))


def _summary_fields(row: HistoryEntry) -> dict[str, Any]:
    return {
        "id": row.id,
        "created_at": row.created_at,
        "source": row.source,
        "group_id": row.group_id,
        "model": row.model,
        "provider": row.provider,
        "status": row.status,
        "prompt_preview": row.rendered_prompt[:PREVIEW_CHARS],
        "output_preview": (row.output or "")[:PREVIEW_CHARS],
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "latency_ms": row.latency_ms,
        "cost_usd": row.cost_usd,
        "finish_reason": row.finish_reason,
        "error_code": row.error_code,
        "prompt_version_id": row.prompt_version_id,
    }


def to_detail(row: HistoryEntry) -> HistoryDetail:
    return HistoryDetail(
        **_summary_fields(row),
        system_template=row.system_template,
        prompt_template=row.prompt_template,
        variables=dict(row.variables or {}),
        rendered_system=row.rendered_system,
        rendered_prompt=row.rendered_prompt,
        params=RunParams(**row.params),
        output=row.output or "",
        thinking=row.thinking,
        error_message=row.error_message,
        ttft_ms=row.ttft_ms,
        request_id=row.request_id,
        warnings=list(row.warnings or []),
    )


async def list_history(
    db: Database,
    *,
    q: str | None,
    model: str | None,
    provider: str | None,
    status: str | None,
    source: str | None,
    group_id: str | None,
    limit: int,
    offset: int,
) -> tuple[list[HistoryEntry], int]:
    filters: list[Any] = []
    if q:
        pattern = like_pattern(q)
        filters.append(
            or_(
                contains_pattern(HistoryEntry.rendered_prompt, pattern),
                contains_pattern(HistoryEntry.rendered_system, pattern),
                contains_pattern(HistoryEntry.output, pattern),
            )
        )
    for column, value in (
        (HistoryEntry.model, model),
        (HistoryEntry.provider, provider),
        (HistoryEntry.status, status),
        (HistoryEntry.source, source),
        (HistoryEntry.group_id, group_id),
    ):
        if value:
            filters.append(column == value)
    async with db.read() as session:
        total = await session.scalar(select(func.count()).select_from(HistoryEntry).where(*filters))
        rows = await session.scalars(
            select(HistoryEntry)
            .where(*filters)
            .order_by(HistoryEntry.created_at.desc(), HistoryEntry.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)


async def get_history(db: Database, history_id: str) -> HistoryEntry:
    async with db.read() as session:
        row = await session.get(HistoryEntry, history_id)
    if row is None:
        raise not_found("history")
    return row


async def delete_history(db: Database, history_id: str) -> None:
    async with db.write() as session:
        result = await session.execute(delete(HistoryEntry).where(HistoryEntry.id == history_id))
        if not result.rowcount:
            raise not_found("history")


async def clear_history(db: Database) -> int:
    async with db.write() as session:
        result = await session.execute(delete(HistoryEntry))
        return int(result.rowcount or 0)
