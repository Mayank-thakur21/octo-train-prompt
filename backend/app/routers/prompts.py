"""Prompt library: prompts, versions, diffs and tags."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.deps import AuthFirstRoute, StateDep, guard
from app.errors import field_error
from app.routers.params import Limit, Offset, VersionNumber, VersionQuery
from app.schemas import (
    PromptCreate,
    PromptDetail,
    PromptPage,
    PromptUpdate,
    TagsResponse,
    VersionCreate,
    VersionDetail,
    VersionDiff,
    VersionPage,
    normalize_tag,
)
from app.services import library
from app.services.validation import parse_id

router = APIRouter(
    prefix="/api", route_class=AuthFirstRoute, tags=["prompts"], dependencies=[guard("default")]
)


@router.get("/prompts", response_model=PromptPage)
async def list_prompts(
    state: StateDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    tag: Annotated[list[str] | None, Query()] = None,
    archived: library.ArchivedFilter = "false",
    sort: library.SortField = "updated_at",
    order: library.SortOrder = "desc",
    limit: Limit = 20,
    offset: Offset = 0,
) -> PromptPage:
    """Search and filter the library (``tag`` is repeatable and combined with AND)."""
    tags: list[str] = []
    for raw in tag or []:
        try:
            tags.append(normalize_tag(raw))
        except ValueError as exc:
            raise field_error(["query", "tag"], str(exc)) from None
    items, total = await library.list_prompts(
        state,
        q=q,
        tags=tags,
        archived=archived,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )
    return PromptPage(items=items, total=total, limit=limit, offset=offset)


@router.post("/prompts", response_model=PromptDetail, status_code=201)
async def create_prompt(body: PromptCreate, state: StateDep) -> PromptDetail:
    """Create a prompt with its first version."""
    return await library.create_prompt(state, body)


@router.get("/prompts/{prompt_id}", response_model=PromptDetail)
async def get_prompt(prompt_id: str, state: StateDep) -> PromptDetail:
    return await library.get_prompt(state, parse_id(prompt_id, "prompt"))


@router.patch("/prompts/{prompt_id}", response_model=PromptDetail)
async def update_prompt(prompt_id: str, body: PromptUpdate, state: StateDep) -> PromptDetail:
    """Rename, describe, retag or (un)archive a prompt."""
    return await library.update_prompt(state, parse_id(prompt_id, "prompt"), body)


@router.delete("/prompts/{prompt_id}", status_code=204, response_class=Response)
async def delete_prompt(prompt_id: str, state: StateDep) -> Response:
    """Delete a prompt with its versions (history and evaluations keep their snapshots)."""
    await library.delete_prompt(state, parse_id(prompt_id, "prompt"))
    return Response(status_code=204)


@router.get("/prompts/{prompt_id}/versions", response_model=VersionPage)
async def list_versions(
    prompt_id: str, state: StateDep, limit: Limit = 20, offset: Offset = 0
) -> VersionPage:
    """Versions, newest first."""
    items, total = await library.list_versions(
        state, parse_id(prompt_id, "prompt"), limit=limit, offset=offset
    )
    return VersionPage(items=items, total=total, limit=limit, offset=offset)


@router.post("/prompts/{prompt_id}/versions", response_model=VersionDetail, status_code=201)
async def create_version(prompt_id: str, body: VersionCreate, state: StateDep) -> VersionDetail:
    """Add a version (409 ``no_changes`` when identical to the latest)."""
    return await library.create_version(state, parse_id(prompt_id, "prompt"), body)


@router.get("/prompts/{prompt_id}/versions/{version}", response_model=VersionDetail)
async def get_version(prompt_id: str, version: VersionNumber, state: StateDep) -> VersionDetail:
    return await library.get_version(state, parse_id(prompt_id, "prompt"), version)


@router.post(
    "/prompts/{prompt_id}/versions/{version}/restore",
    response_model=VersionDetail,
    status_code=201,
)
async def restore_version(prompt_id: str, version: VersionNumber, state: StateDep) -> VersionDetail:
    """Create a new latest version copying an older one."""
    return await library.restore_version(state, parse_id(prompt_id, "prompt"), version)


@router.get("/prompts/{prompt_id}/diff", response_model=VersionDiff)
async def diff_versions(
    prompt_id: str,
    state: StateDep,
    from_version: VersionQuery,
    to_version: VersionQuery,
) -> VersionDiff:
    """Line diff of system and prompt between two versions."""
    return await library.diff_versions(
        state, parse_id(prompt_id, "prompt"), from_version, to_version
    )


@router.get("/prompt-versions/{version_id}", response_model=VersionDetail)
async def get_version_by_id(version_id: str, state: StateDep) -> VersionDetail:
    return await library.get_version_by_id(state, parse_id(version_id, "prompt_version"))


@router.get("/tags", response_model=TagsResponse)
async def list_tags(state: StateDep) -> TagsResponse:
    """Tags with prompt counts, most used first."""
    return TagsResponse(tags=await library.tag_counts(state))
