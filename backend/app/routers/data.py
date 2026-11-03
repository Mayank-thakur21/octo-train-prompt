"""Export and import of the prompt library, suites and (optionally) history."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.db import utcnow
from app.deps import AuthFirstRoute, StateDep, guard
from app.errors import from_pydantic
from app.schemas import ExportDocument, ImportDocument, ImportResult
from app.services import export

router = APIRouter(
    prefix="/api", route_class=AuthFirstRoute, tags=["data"], dependencies=[guard("data")]
)


@router.get("/export", response_model=ExportDocument, response_class=JSONResponse)
async def export_data(
    state: StateDep,
    include: Annotated[str, Query(max_length=100)] = "prompts,suites",
) -> JSONResponse:
    """Download prompts (all versions) and suites, plus history when requested."""
    sections = export.parse_include(include)
    document = await export.build_export(state, sections)
    filename = export.export_filename(utcnow())
    return JSONResponse(
        document, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.post("/import", response_model=ImportResult)
async def import_data(
    state: StateDep,
    document: Annotated[dict[str, Any], Body()],
    conflict: Annotated[export.ConflictPolicy, Query()] = "skip",
    legacy_placeholders: Annotated[bool, Query()] = False,
) -> ImportResult:
    """Import an export document in one transaction (all or nothing)."""
    export.check_format(document)
    try:
        parsed = ImportDocument.model_validate(document)
    except ValidationError as exc:
        raise from_pydantic(exc) from None
    return await export.import_document(state, parsed, policy=conflict, legacy=legacy_placeholders)
