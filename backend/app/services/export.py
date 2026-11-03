"""Export documents and imports with a conflict policy (one all-or-nothing transaction)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.db import new_id, utcnow
from app.errors import AppError, field_error, limit_exceeded
from app.models import HistoryEntry, Prompt, PromptVersion, TestCase, TestSuite
from app.schemas import (
    ExportPrompt,
    ExportSuite,
    HistoryImportCount,
    ImportCounts,
    ImportDocument,
    ImportResult,
    format_timestamp,
)
from app.services import history as history_service
from app.services import templating
from app.services.evaluation import normalize_assertions, validate_case_assertions
from app.services.library import same_content, set_tags, settings_dict
from app.services.validation import check_template, check_variables
from app.state import AppState

EXPORT_FORMAT = "prompt-studio-export"
EXPORT_FORMAT_VERSION = 1
INCLUDE_VALUES = ("prompts", "suites", "history")
MAX_IMPORT_PROMPTS = 1000
MAX_IMPORT_SUITES = 200
NAME_MAX = 120

ConflictPolicy = Literal["skip", "rename", "overwrite"]


def _ts(value: datetime) -> str:
    return format_timestamp(value)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


# ---- export ----------------------------------------------------------------------------------


def parse_include(raw: str) -> set[str]:
    values = {item.strip() for item in raw.split(",") if item.strip()}
    unknown = sorted(values - set(INCLUDE_VALUES))
    if unknown:
        raise field_error(
            ["query", "include"],
            "include must be a comma list of: " + ", ".join(INCLUDE_VALUES),
            "enum",
        )
    return values


async def build_export(state: AppState, include: set[str]) -> dict[str, Any]:
    """The export document as a JSON-ready dict."""
    prompts: list[dict[str, Any]] = []
    suites: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    async with state.db.read() as session:
        if "prompts" in include:
            versions_by_prompt: dict[str, list[PromptVersion]] = {}
            for version in await session.scalars(
                select(PromptVersion).order_by(PromptVersion.prompt_id, PromptVersion.version)
            ):
                versions_by_prompt.setdefault(version.prompt_id, []).append(version)
            for prompt in await session.scalars(
                select(Prompt).order_by(Prompt.created_at, Prompt.id)
            ):
                prompts.append(
                    {
                        "id": prompt.id,
                        "name": prompt.name,
                        "description": prompt.description,
                        "tags": prompt.tag_names,
                        "archived": prompt.archived,
                        "created_at": _ts(prompt.created_at),
                        "updated_at": _ts(prompt.updated_at),
                        "versions": [
                            {
                                "id": version.id,
                                "version": version.version,
                                "system": version.system,
                                "prompt": version.prompt,
                                "notes": version.notes,
                                "settings": settings_dict(version.settings),
                                "created_at": _ts(version.created_at),
                            }
                            for version in versions_by_prompt.get(prompt.id, [])
                        ],
                    }
                )
        if "suites" in include:
            cases_by_suite: dict[str, list[TestCase]] = {}
            for case in await session.scalars(
                select(TestCase).order_by(TestCase.suite_id, TestCase.position)
            ):
                cases_by_suite.setdefault(case.suite_id, []).append(case)
            for suite in await session.scalars(
                select(TestSuite).order_by(TestSuite.created_at, TestSuite.id)
            ):
                suites.append(
                    {
                        "id": suite.id,
                        "name": suite.name,
                        "description": suite.description,
                        "created_at": _ts(suite.created_at),
                        "updated_at": _ts(suite.updated_at),
                        "cases": [
                            {
                                "id": case.id,
                                "name": case.name,
                                "variables": dict(case.variables or {}),
                                "assertions": list(case.assertions or []),
                                "position": case.position,
                                "created_at": _ts(case.created_at),
                                "updated_at": _ts(case.updated_at),
                            }
                            for case in cases_by_suite.get(suite.id, [])
                        ],
                    }
                )
        if "history" in include:
            rows = await session.scalars(
                select(HistoryEntry)
                .order_by(HistoryEntry.created_at.desc(), HistoryEntry.id.desc())
                .limit(state.settings.history_max_rows)
            )
            entries = [history_service.to_detail(row).model_dump(mode="json") for row in rows]
    return {
        "format": EXPORT_FORMAT,
        "format_version": EXPORT_FORMAT_VERSION,
        "exported_at": _ts(utcnow()),
        "app_version": __version__,
        "prompts": prompts,
        "suites": suites,
        "history": entries,
    }


def export_filename(now: datetime) -> str:
    return f"prompt-studio-export-{now.astimezone(UTC):%Y%m%d-%H%M%S}.json"


# ---- import validation -----------------------------------------------------------------------


def check_format(raw: Any) -> None:
    """``unsupported_format`` unless the document declares the supported format and version."""
    if (
        not isinstance(raw, dict)
        or raw.get("format") != EXPORT_FORMAT
        or raw.get("format_version") != EXPORT_FORMAT_VERSION
        or isinstance(raw.get("format_version"), bool)
    ):
        raise AppError(
            422,
            "unsupported_format",
            f"Only {EXPORT_FORMAT} documents with format_version {EXPORT_FORMAT_VERSION} "
            "can be imported.",
        )


def _check_unique_names(items: Iterable[Any], section: str) -> None:
    seen: set[str] = set()
    for index, item in enumerate(items):
        key = item.name.casefold()
        if key in seen:
            raise field_error(
                ["body", section, index, "name"],
                f"Duplicate name in the import file: {item.name}",
                "duplicate_name",
            )
        seen.add(key)


def validate_document(state: AppState, doc: ImportDocument, *, legacy: bool) -> None:
    settings = state.settings
    if len(doc.prompts) > MAX_IMPORT_PROMPTS:
        raise limit_exceeded("max_import_prompts", MAX_IMPORT_PROMPTS)
    if len(doc.suites) > MAX_IMPORT_SUITES:
        raise limit_exceeded("max_import_suites", MAX_IMPORT_SUITES)
    if len(doc.history) > settings.history_max_rows:
        raise limit_exceeded("history_max_rows", settings.history_max_rows)
    _check_unique_names(doc.prompts, "prompts")
    _check_unique_names(doc.suites, "suites")
    for p_index, prompt in enumerate(doc.prompts):
        if len(prompt.tags) > settings.max_tags_per_prompt:
            raise limit_exceeded("max_tags_per_prompt", settings.max_tags_per_prompt)
        if len(prompt.versions) > settings.max_versions_per_prompt:
            raise limit_exceeded("max_versions_per_prompt", settings.max_versions_per_prompt)
        for v_index, version in enumerate(prompt.versions):
            system, text = _version_texts(version.system, version.prompt, legacy)
            check_template(
                settings,
                system=system,
                prompt=text,
                loc=("body", "prompts", p_index, "versions", v_index),
            )
    for s_index, suite in enumerate(doc.suites):
        if len(suite.cases) > settings.max_cases_per_suite:
            raise limit_exceeded("max_cases_per_suite", settings.max_cases_per_suite)
        for c_index, case in enumerate(suite.cases):
            check_variables(
                settings, case.variables, ("body", "suites", s_index, "cases", c_index, "variables")
            )
            validate_case_assertions(
                state, case.assertions, case_index=c_index, extra={"suite_index": s_index}
            )


def _version_texts(system: str | None, prompt: str, legacy: bool) -> tuple[str | None, str]:
    if not legacy:
        return system, prompt
    return (
        templating.convert_legacy_placeholders(system) if system is not None else None,
        templating.convert_legacy_placeholders(prompt),
    )


# ---- import ----------------------------------------------------------------------------------


def _renamed(base: str, taken: set[str]) -> str:
    attempt = 1
    while True:
        suffix = " (imported)" if attempt == 1 else f" (imported {attempt})"
        candidate = base[: NAME_MAX - len(suffix)].rstrip() + suffix
        if candidate.casefold() not in taken:
            return candidate
        attempt += 1


class _Importer:
    def __init__(
        self,
        state: AppState,
        session: AsyncSession,
        policy: ConflictPolicy,
        legacy: bool,
        file_names: dict[str, set[str]],
    ) -> None:
        self.state = state
        self.session = session
        self.policy = policy
        self.legacy = legacy
        self.file_names = file_names
        self.version_ids: dict[str, str] = {}
        self.prompts = ImportCounts()
        self.suites = ImportCounts()
        self.warnings: list[str] = []

    async def _existing_names(self, model: type[Prompt] | type[TestSuite]) -> dict[str, Any]:
        rows = await self.session.scalars(select(model))
        return {row.name_key: row for row in rows}

    async def import_prompts(self, prompts: list[ExportPrompt]) -> None:
        existing = await self._existing_names(Prompt)
        taken = set(existing) | self.file_names["prompts"]
        for item in prompts:
            current = existing.get(item.name.casefold())
            if current is None:
                await self._create_prompt(item, item.name)
                self.prompts.created += 1
                taken.add(item.name.casefold())
            elif self.policy == "skip":
                self.prompts.skipped += 1
            elif self.policy == "rename":
                name = _renamed(item.name, taken)
                taken.add(name.casefold())
                await self._create_prompt(item, name)
                self.prompts.renamed += 1
            else:
                await self._overwrite_prompt(current, item)
                self.prompts.updated += 1

    async def _create_prompt(self, item: ExportPrompt, name: str) -> None:
        prompt_id = new_id()
        ordered = sorted(item.versions, key=lambda version: version.version)
        self.session.add(
            Prompt(
                id=prompt_id,
                name=name,
                name_key=name.casefold(),
                description=item.description,
                archived=item.archived,
                latest_version=len(ordered),
                created_at=_aware(item.created_at),
                updated_at=_aware(item.updated_at),
            )
        )
        await self.session.flush()
        for number, version in enumerate(ordered, start=1):
            system, text = _version_texts(version.system, version.prompt, self.legacy)
            new_version_id = new_id()
            self.session.add(
                PromptVersion(
                    id=new_version_id,
                    prompt_id=prompt_id,
                    version=number,
                    system=system,
                    prompt=text,
                    notes=version.notes,
                    settings=settings_dict(version.settings),
                    created_at=_aware(version.created_at),
                )
            )
            self.version_ids[version.id] = new_version_id
        await set_tags(self.session, prompt_id, item.tags)

    async def _overwrite_prompt(self, current: Prompt, item: ExportPrompt) -> None:
        current.description = item.description
        current.archived = item.archived
        await set_tags(self.session, current.id, item.tags)
        versions = list(
            await self.session.scalars(
                select(PromptVersion).where(PromptVersion.prompt_id == current.id)
            )
        )
        latest = max(version.version for version in versions)
        for version in sorted(item.versions, key=lambda entry: entry.version):
            system, text = _version_texts(version.system, version.prompt, self.legacy)
            settings = settings_dict(version.settings)
            if any(same_content(existing, system, text, settings) for existing in versions):
                continue
            if latest >= self.state.settings.max_versions_per_prompt:
                raise limit_exceeded(
                    "max_versions_per_prompt", self.state.settings.max_versions_per_prompt
                )
            latest += 1
            created = PromptVersion(
                id=new_id(),
                prompt_id=current.id,
                version=latest,
                system=system,
                prompt=text,
                notes=version.notes,
                settings=settings,
                created_at=_aware(version.created_at),
            )
            self.session.add(created)
            versions.append(created)
            self.version_ids[version.id] = created.id
        current.latest_version = latest
        current.updated_at = utcnow()

    async def import_suites(self, suites: list[ExportSuite]) -> None:
        existing = await self._existing_names(TestSuite)
        taken = set(existing) | self.file_names["suites"]
        for item in suites:
            current = existing.get(item.name.casefold())
            if current is None:
                await self._create_suite(item, item.name)
                self.suites.created += 1
                taken.add(item.name.casefold())
            elif self.policy == "skip":
                self.suites.skipped += 1
            elif self.policy == "rename":
                name = _renamed(item.name, taken)
                taken.add(name.casefold())
                await self._create_suite(item, name)
                self.suites.renamed += 1
            else:
                current.description = item.description
                current.updated_at = utcnow()
                for case in await self.session.scalars(
                    select(TestCase).where(TestCase.suite_id == current.id)
                ):
                    await self.session.delete(case)
                await self.session.flush()
                self._add_cases(current.id, item)
                self.suites.updated += 1

    async def _create_suite(self, item: ExportSuite, name: str) -> None:
        suite_id = new_id()
        self.session.add(
            TestSuite(
                id=suite_id,
                name=name,
                name_key=name.casefold(),
                description=item.description,
                created_at=_aware(item.created_at),
                updated_at=_aware(item.updated_at),
            )
        )
        await self.session.flush()
        self._add_cases(suite_id, item)

    def _add_cases(self, suite_id: str, item: ExportSuite) -> None:
        ordered = sorted(item.cases, key=lambda case: case.position)
        for position, case in enumerate(ordered):
            self.session.add(
                TestCase(
                    id=new_id(),
                    suite_id=suite_id,
                    name=case.name,
                    variables=dict(case.variables),
                    assertions=normalize_assertions(case.assertions),
                    position=position,
                    created_at=_aware(case.created_at),
                    updated_at=_aware(case.updated_at),
                )
            )

    def history_rows(self, doc: ImportDocument) -> list[HistoryEntry]:
        rows: list[HistoryEntry] = []
        for number, entry in enumerate(doc.history, start=1):
            version_id: str | None = None
            if entry.prompt_version_id is not None:
                version_id = self.version_ids.get(entry.prompt_version_id)
                if version_id is None:
                    self.warnings.append(
                        f"History entry {number} references a version that was not imported."
                    )
            rows.append(
                HistoryEntry(
                    id=new_id(),
                    created_at=_aware(entry.created_at),
                    source=entry.source,
                    group_id=entry.group_id,
                    prompt_version_id=version_id,
                    model=entry.model,
                    provider=entry.provider,
                    status=entry.status,
                    system_template=entry.system_template,
                    prompt_template=entry.prompt_template,
                    variables=dict(entry.variables),
                    rendered_system=entry.rendered_system,
                    rendered_prompt=entry.rendered_prompt,
                    params=entry.params.model_dump(),
                    output=entry.output,
                    thinking=entry.thinking,
                    input_tokens=entry.input_tokens,
                    output_tokens=entry.output_tokens,
                    latency_ms=entry.latency_ms,
                    ttft_ms=entry.ttft_ms,
                    finish_reason=entry.finish_reason,
                    request_id=entry.request_id,
                    cost_usd=entry.cost_usd,
                    warnings=list(entry.warnings),
                    error_code=entry.error_code,
                    error_message=entry.error_message,
                )
            )
        return rows


async def import_document(
    state: AppState, doc: ImportDocument, *, policy: ConflictPolicy, legacy: bool
) -> ImportResult:
    """Validate the whole document, then import it in one transaction."""
    validate_document(state, doc, legacy=legacy)
    file_names = {
        "prompts": {item.name.casefold() for item in doc.prompts},
        "suites": {item.name.casefold() for item in doc.suites},
    }
    async with state.db.write() as session:
        importer = _Importer(state, session, policy, legacy, file_names)
        await importer.import_prompts(doc.prompts)
        await importer.import_suites(doc.suites)
        await session.flush()
        rows = importer.history_rows(doc)
        session.add_all(rows)
        await session.flush()
        if rows:
            await history_service.prune(session, state.settings.history_max_rows)
    return ImportResult(
        prompts=importer.prompts,
        suites=importer.suites,
        history=HistoryImportCount(created=len(rows)),
        warnings=importer.warnings,
    )
