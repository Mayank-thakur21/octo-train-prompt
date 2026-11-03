"""Prompt library: prompts with immutable versions, tags, search and diffs."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import new_id, utcnow
from app.errors import AppError, conflict, limit_exceeded, not_found
from app.models import Prompt, PromptTag, PromptVersion
from app.schemas import (
    PromptCreate,
    PromptDetail,
    PromptSettings,
    PromptSummary,
    PromptUpdate,
    TagCount,
    VariableInfoOut,
    VersionCreate,
    VersionDetail,
    VersionDiff,
    VersionSummary,
)
from app.services import templating
from app.services.diff import diff_text
from app.services.history import contains_pattern, like_pattern
from app.services.validation import check_template
from app.state import AppState

SortField = Literal["updated_at", "created_at", "name"]
SortOrder = Literal["asc", "desc"]
ArchivedFilter = Literal["false", "true", "all"]


# ---- conversions -----------------------------------------------------------------------------


def settings_dict(settings: PromptSettings | dict[str, Any] | None) -> dict[str, Any]:
    """A normalized ``PromptSettings`` dict (every key present)."""
    if isinstance(settings, PromptSettings):
        return settings.model_dump()
    return PromptSettings(**(settings or {})).model_dump()


def version_summary(version: PromptVersion) -> VersionSummary:
    return VersionSummary(
        id=version.id,
        prompt_id=version.prompt_id,
        version=version.version,
        notes=version.notes,
        created_at=version.created_at,
        variables=templating.variable_names(version.system, version.prompt),
    )


def version_detail(version: PromptVersion) -> VersionDetail:
    return VersionDetail(
        id=version.id,
        prompt_id=version.prompt_id,
        version=version.version,
        system=version.system,
        prompt=version.prompt,
        notes=version.notes,
        settings=PromptSettings(**settings_dict(version.settings)),
        variables=[
            VariableInfoOut(**info.as_dict())
            for info in templating.extract_variables(version.system, version.prompt)
        ],
        created_at=version.created_at,
    )


def _prompt_fields(prompt: Prompt, version_count: int) -> dict[str, Any]:
    return {
        "id": prompt.id,
        "name": prompt.name,
        "description": prompt.description,
        "tags": prompt.tag_names,
        "archived": prompt.archived,
        "created_at": prompt.created_at,
        "updated_at": prompt.updated_at,
        "version_count": version_count,
    }


def _version_count_subquery() -> Any:
    return (
        select(func.count(PromptVersion.id))
        .where(PromptVersion.prompt_id == Prompt.id)
        .correlate(Prompt)
        .scalar_subquery()
    )


def _with_latest() -> Any:
    return select(Prompt, PromptVersion, _version_count_subquery()).join(
        PromptVersion,
        and_(PromptVersion.prompt_id == Prompt.id, PromptVersion.version == Prompt.latest_version),
    )


# ---- helpers ---------------------------------------------------------------------------------


async def _name_taken(session: AsyncSession, name: str, exclude_id: str | None = None) -> bool:
    stmt = select(Prompt.id).where(Prompt.name_key == name.casefold())
    if exclude_id is not None:
        stmt = stmt.where(Prompt.id != exclude_id)
    return (await session.scalar(stmt)) is not None


def _check_tags(state: AppState, tags: list[str]) -> None:
    if len(tags) > state.settings.max_tags_per_prompt:
        raise limit_exceeded("max_tags_per_prompt", state.settings.max_tags_per_prompt)


async def set_tags(session: AsyncSession, prompt_id: str, tags: list[str]) -> None:
    await session.execute(delete(PromptTag).where(PromptTag.prompt_id == prompt_id))
    for position, tag in enumerate(tags):
        session.add(PromptTag(prompt_id=prompt_id, tag=tag, position=position))


async def _load_prompt(session: AsyncSession, prompt_id: str) -> Prompt:
    prompt = await session.get(Prompt, prompt_id)
    if prompt is None:
        raise not_found("prompt")
    return prompt


async def _latest(session: AsyncSession, prompt: Prompt) -> PromptVersion:
    version = await session.scalar(
        select(PromptVersion).where(
            PromptVersion.prompt_id == prompt.id, PromptVersion.version == prompt.latest_version
        )
    )
    if version is None:  # every prompt is created with a first version
        raise not_found("prompt_version")
    return version


def same_content(
    version: PromptVersion, system: str | None, prompt: str, settings: dict[str, Any]
) -> bool:
    return (
        version.system == system
        and version.prompt == prompt
        and settings_dict(version.settings) == settings
    )


# ---- prompts ---------------------------------------------------------------------------------


async def get_prompt(state: AppState, prompt_id: str) -> PromptDetail:
    async with state.db.read() as session:
        row = (await session.execute(_with_latest().where(Prompt.id == prompt_id))).first()
    if row is None:
        raise not_found("prompt")
    prompt, latest, count = row
    return PromptDetail(**_prompt_fields(prompt, int(count)), latest_version=version_detail(latest))


async def create_prompt(state: AppState, req: PromptCreate) -> PromptDetail:
    check_template(state.settings, system=req.system, prompt=req.prompt)
    _check_tags(state, req.tags)
    prompt_id = new_id()
    async with state.db.write() as session:
        if await _name_taken(session, req.name):
            raise conflict()
        now = utcnow()
        session.add(
            Prompt(
                id=prompt_id,
                name=req.name,
                name_key=req.name.casefold(),
                description=req.description,
                archived=False,
                latest_version=1,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            PromptVersion(
                prompt_id=prompt_id,
                version=1,
                system=req.system,
                prompt=req.prompt,
                notes=req.notes,
                settings=settings_dict(req.settings),
                created_at=now,
            )
        )
        await set_tags(session, prompt_id, req.tags)
    return await get_prompt(state, prompt_id)


async def update_prompt(state: AppState, prompt_id: str, req: PromptUpdate) -> PromptDetail:
    if req.tags is not None:
        _check_tags(state, req.tags)
    async with state.db.write() as session:
        prompt = await _load_prompt(session, prompt_id)
        if req.name is not None and req.name != prompt.name:
            if await _name_taken(session, req.name, exclude_id=prompt_id):
                raise conflict()
            prompt.name = req.name
            prompt.name_key = req.name.casefold()
        if req.description is not None:
            prompt.description = req.description
        if req.archived is not None:
            prompt.archived = req.archived
        if req.tags is not None:
            await set_tags(session, prompt_id, req.tags)
        prompt.updated_at = utcnow()
    return await get_prompt(state, prompt_id)


async def delete_prompt(state: AppState, prompt_id: str) -> None:
    async with state.db.write() as session:
        prompt = await _load_prompt(session, prompt_id)
        await session.delete(prompt)


async def list_prompts(
    state: AppState,
    *,
    q: str | None,
    tags: list[str],
    archived: ArchivedFilter,
    sort: SortField,
    order: SortOrder,
    limit: int,
    offset: int,
) -> tuple[list[PromptSummary], int]:
    filters: list[Any] = []
    if archived != "all":
        filters.append(Prompt.archived.is_(archived == "true"))
    for tag in tags:
        filters.append(Prompt.id.in_(select(PromptTag.prompt_id).where(PromptTag.tag == tag)))
    if q:
        pattern = like_pattern(q)
        filters.append(
            or_(
                contains_pattern(Prompt.name, pattern),
                contains_pattern(Prompt.description, pattern),
                contains_pattern(func.coalesce(PromptVersion.system, ""), pattern),
                contains_pattern(PromptVersion.prompt, pattern),
            )
        )
    column = {
        "updated_at": Prompt.updated_at,
        "created_at": Prompt.created_at,
        "name": Prompt.name_key,
    }[sort]
    ordering = (
        [column.asc(), Prompt.id.asc()] if order == "asc" else [column.desc(), Prompt.id.desc()]
    )
    joined = and_(
        PromptVersion.prompt_id == Prompt.id, PromptVersion.version == Prompt.latest_version
    )
    async with state.db.read() as session:
        total = await session.scalar(
            select(func.count(Prompt.id)).join(PromptVersion, joined).where(*filters)
        )
        rows = (
            await session.execute(
                _with_latest().where(*filters).order_by(*ordering).limit(limit).offset(offset)
            )
        ).all()
    items = [
        PromptSummary(**_prompt_fields(prompt, int(count)), latest_version=version_summary(latest))
        for prompt, latest, count in rows
    ]
    return items, int(total or 0)


async def tag_counts(state: AppState) -> list[TagCount]:
    async with state.db.read() as session:
        rows = (
            await session.execute(
                select(PromptTag.tag, func.count(PromptTag.prompt_id).label("count"))
                .group_by(PromptTag.tag)
                .order_by(func.count(PromptTag.prompt_id).desc(), PromptTag.tag.asc())
            )
        ).all()
    return [TagCount(tag=tag, count=int(count)) for tag, count in rows]


# ---- versions --------------------------------------------------------------------------------


async def _append_version(
    state: AppState,
    session: AsyncSession,
    prompt: Prompt,
    *,
    system: str | None,
    prompt_text: str,
    notes: str,
    settings: dict[str, Any],
) -> PromptVersion:
    latest = await _latest(session, prompt)
    if same_content(latest, system, prompt_text, settings):
        raise AppError(409, "no_changes", "No changes since the latest version.")
    if prompt.latest_version >= state.settings.max_versions_per_prompt:
        raise limit_exceeded("max_versions_per_prompt", state.settings.max_versions_per_prompt)
    now = utcnow()
    version = PromptVersion(
        id=new_id(),
        prompt_id=prompt.id,
        version=prompt.latest_version + 1,
        system=system,
        prompt=prompt_text,
        notes=notes,
        settings=settings,
        created_at=now,
    )
    session.add(version)
    prompt.latest_version = version.version
    prompt.updated_at = now
    return version


async def create_version(state: AppState, prompt_id: str, req: VersionCreate) -> VersionDetail:
    check_template(state.settings, system=req.system, prompt=req.prompt)
    async with state.db.write() as session:
        prompt = await _load_prompt(session, prompt_id)
        version = await _append_version(
            state,
            session,
            prompt,
            system=req.system,
            prompt_text=req.prompt,
            notes=req.notes,
            settings=settings_dict(req.settings),
        )
    return version_detail(version)


async def restore_version(state: AppState, prompt_id: str, number: int) -> VersionDetail:
    async with state.db.write() as session:
        prompt = await _load_prompt(session, prompt_id)
        source = await _version_by_number(session, prompt_id, number)
        version = await _append_version(
            state,
            session,
            prompt,
            system=source.system,
            prompt_text=source.prompt,
            notes=f"Restored from v{number}",
            settings=settings_dict(source.settings),
        )
    return version_detail(version)


async def _version_by_number(session: AsyncSession, prompt_id: str, number: int) -> PromptVersion:
    version = await session.scalar(
        select(PromptVersion).where(
            PromptVersion.prompt_id == prompt_id, PromptVersion.version == number
        )
    )
    if version is None:
        raise not_found("prompt_version")
    return version


async def list_versions(
    state: AppState, prompt_id: str, *, limit: int, offset: int
) -> tuple[list[VersionSummary], int]:
    async with state.db.read() as session:
        await _load_prompt(session, prompt_id)
        total = await session.scalar(
            select(func.count(PromptVersion.id)).where(PromptVersion.prompt_id == prompt_id)
        )
        versions = await session.scalars(
            select(PromptVersion)
            .where(PromptVersion.prompt_id == prompt_id)
            .order_by(PromptVersion.version.desc())
            .limit(limit)
            .offset(offset)
        )
        return [version_summary(version) for version in versions], int(total or 0)


async def get_version(state: AppState, prompt_id: str, number: int) -> VersionDetail:
    async with state.db.read() as session:
        await _load_prompt(session, prompt_id)
        return version_detail(await _version_by_number(session, prompt_id, number))


async def get_version_by_id(state: AppState, version_id: str) -> VersionDetail:
    async with state.db.read() as session:
        version = await session.get(PromptVersion, version_id)
    if version is None:
        raise not_found("prompt_version")
    return version_detail(version)


async def diff_versions(
    state: AppState, prompt_id: str, from_version: int, to_version: int
) -> VersionDiff:
    async with state.db.read() as session:
        await _load_prompt(session, prompt_id)
        old = await _version_by_number(session, prompt_id, from_version)
        new = await _version_by_number(session, prompt_id, to_version)
    settings_from = settings_dict(old.settings)
    settings_to = settings_dict(new.settings)
    # The diff work is bounded (see services/diff.py) but can still take a moment on very
    # large versions, so it runs in a worker thread instead of on the event loop.
    system_diff, prompt_diff = await asyncio.to_thread(
        lambda: (
            diff_text(old.system, new.system, from_version, to_version),
            diff_text(old.prompt, new.prompt, from_version, to_version),
        )
    )
    return VersionDiff(
        prompt_id=prompt_id,
        from_version=from_version,
        to_version=to_version,
        system=system_diff,
        prompt=prompt_diff,
        settings_changed=settings_from != settings_to,
        settings_from=PromptSettings(**settings_from),
        settings_to=PromptSettings(**settings_to),
        notes_from=old.notes,
        notes_to=new.notes,
    )
