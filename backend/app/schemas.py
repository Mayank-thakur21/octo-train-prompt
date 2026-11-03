"""Pydantic request and response models (the wire contract, snake_case JSON).

Request models reject unknown fields. Name-like strings are trimmed before validation;
prompt, system and variable values are never trimmed. Limits that depend on settings
(prompt sizes, variable counts, caps) are checked by the services.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    field_validator,
)

# ---- primitives ------------------------------------------------------------------------------


def format_timestamp(value: datetime) -> str:
    """RFC 3339 UTC with microseconds and a ``Z`` suffix."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


Timestamp = Annotated[datetime, PlainSerializer(format_timestamp, return_type=str)]
ProviderId = Literal["anthropic", "openai", "gemini", "demo"]
FinishReasonValue = Literal["stop", "length", "content_filter", "refusal", "other"]
EvalStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
CaseResultStatus = Literal["pending", "passed", "failed", "error"]
HistoryStatus = Literal["success", "error", "cancelled"]

TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
VARIABLE_KEY_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"

Name120 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Name200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Label60 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
ModelId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
RefId = Annotated[str, StringConstraints(min_length=1, max_length=64)]
VariableKey = Annotated[str, StringConstraints(pattern=VARIABLE_KEY_PATTERN)]
Variables = dict[VariableKey, str]
Temperature = Annotated[float, Field(ge=0.0, le=2.0, allow_inf_nan=False)]
MaxTokens = Annotated[int, Field(ge=1)]
# Largest integer accepted where a value is stored in an INTEGER column or bound into a query
# (SQLite integers are 8 bytes; this keeps a wide margin and fits every client).
MAX_STORED_INT = 2**31 - 1
StoredCount = Annotated[int, Field(ge=0, le=MAX_STORED_INT)]


def normalize_tag(raw: str) -> str:
    """Trim, lowercase and collapse whitespace runs to ``-``; raises ``ValueError`` if invalid."""
    tag = re.sub(r"\s+", "-", raw.strip().lower())
    if not TAG_PATTERN.match(tag):
        raise ValueError(
            "tags must be 1-32 characters of lowercase letters, digits, '-' or '_' "
            "and start with a letter or digit"
        )
    return tag


def normalize_tags(values: list[str]) -> list[str]:
    seen: list[str] = []
    for raw in values:
        tag = normalize_tag(raw)
        if tag not in seen:
            seen.append(tag)
    return seen


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ---- errors ----------------------------------------------------------------------------------


class ErrorBody(ResponseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorEnvelope(ResponseModel):
    error: ErrorBody


# ---- meta / models ---------------------------------------------------------------------------


class LongContextPricing(ResponseModel):
    threshold_input_tokens: int
    input_per_mtok: float
    output_per_mtok: float


class PricingOut(ResponseModel):
    currency: Literal["USD"] = "USD"
    input_per_mtok: float
    output_per_mtok: float
    long_context: LongContextPricing | None


class ModelInfo(ResponseModel):
    id: str
    provider: ProviderId
    display_name: str
    available: bool
    is_default: bool
    supports_thinking: bool
    thinking_always_on: bool
    supports_temperature: bool
    max_output_tokens: int
    context_window: int | None
    pricing: PricingOut | None


class ModelsResponse(ResponseModel):
    models: list[ModelInfo]
    default_model: str


class ProviderInfo(ResponseModel):
    id: ProviderId
    display_name: str
    configured: bool


class Limits(ResponseModel):
    max_prompt_chars: int
    max_system_chars: int
    max_rendered_chars: int
    max_variables: int
    max_variable_value_chars: int
    max_output_tokens: int
    default_max_tokens: int
    max_compare_variants: int
    max_compare_models: int
    max_compare_cells: int
    max_cases_per_suite: int
    max_assertions_per_case: int
    max_eval_models: int
    max_eval_calls: int
    max_tags_per_prompt: int
    max_versions_per_prompt: int
    max_body_bytes: int
    import_max_bytes: int
    request_timeout_seconds: float


class Meta(ResponseModel):
    name: Literal["Prompt Engineering Studio"] = "Prompt Engineering Studio"
    version: str
    auth_required: bool
    demo_mode: bool
    default_model: str
    providers: list[ProviderInfo]
    limits: Limits


class HealthResponse(ResponseModel):
    status: Literal["ok"] = "ok"
    version: str
    time: Timestamp


class ReadyResponse(ResponseModel):
    status: Literal["ready"] = "ready"
    checks: dict[str, str]


# ---- templates -------------------------------------------------------------------------------


class VariableInfoOut(ResponseModel):
    name: str
    default: str | None
    required: bool


class BuiltinTemplateOut(ResponseModel):
    id: str
    name: str
    description: str
    tags: list[str]
    system: str | None
    prompt: str
    variables: list[VariableInfoOut]


class TemplatesResponse(ResponseModel):
    templates: list[BuiltinTemplateOut]


class RenderRequest(RequestModel):
    system: str | None = None
    prompt: str
    variables: Variables = Field(default_factory=dict)
    strict: bool = True


class RenderResult(ResponseModel):
    system: str | None
    prompt: str
    variables: list[VariableInfoOut]
    missing: list[str]


# ---- runs ------------------------------------------------------------------------------------


class RunParams(ResponseModel):
    temperature: float | None
    max_tokens: int
    thinking: bool


class RunRequest(RequestModel):
    model: ModelId | None = None
    system: str | None = None
    prompt: str = Field(min_length=1)
    variables: Variables = Field(default_factory=dict)
    temperature: Temperature | None = None
    max_tokens: MaxTokens | None = None
    thinking: bool = False
    prompt_version_id: RefId | None = None
    save_history: bool = True


class RunResult(ResponseModel):
    id: str | None
    created_at: Timestamp
    model: str
    provider: ProviderId
    text: str
    thinking: str | None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    ttft_ms: int | None
    finish_reason: FinishReasonValue
    request_id: str | None
    cost_usd: float | None
    warnings: list[str]
    rendered_system: str | None
    rendered_prompt: str
    params: RunParams


class RunStartEvent(ResponseModel):
    run_id: str | None
    model: str
    provider: ProviderId
    created_at: Timestamp
    warnings: list[str]


class RunDeltaEvent(ResponseModel):
    type: Literal["text", "thinking"]
    text: str


# ---- tokens ----------------------------------------------------------------------------------


class TokenEstimateRequest(RequestModel):
    model: ModelId | None = None
    system: str | None = None
    prompt: str
    variables: Variables = Field(default_factory=dict)


class TokenEstimate(ResponseModel):
    model: str
    provider: ProviderId
    input_tokens: int
    method: Literal["heuristic", "anthropic_count_tokens"]
    characters: int
    words: int
    warnings: list[str]


# ---- prompts library -------------------------------------------------------------------------


class PromptSettings(BaseModel):
    """Saved run settings of a prompt version (request and response shape)."""

    model_config = ConfigDict(extra="forbid")

    model: ModelId | None = None
    temperature: Temperature | None = None
    max_tokens: MaxTokens | None = None
    thinking: bool = False


def _validate_tags(value: list[str] | None) -> list[str] | None:
    return normalize_tags(value) if value is not None else None


class PromptCreate(RequestModel):
    name: Name120
    description: Description = ""
    tags: list[str] = Field(default_factory=list)
    system: str | None = None
    prompt: str = Field(min_length=1)
    notes: Notes = ""
    settings: PromptSettings = Field(default_factory=PromptSettings)

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str]) -> list[str]:
        return normalize_tags(value)


class PromptUpdate(RequestModel):
    name: Name120 | None = None
    description: Description | None = None
    tags: list[str] | None = None
    archived: bool | None = None

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str] | None) -> list[str] | None:
        return _validate_tags(value)


class VersionCreate(RequestModel):
    system: str | None = None
    prompt: str = Field(min_length=1)
    notes: Notes = ""
    settings: PromptSettings = Field(default_factory=PromptSettings)


class VersionSummary(ResponseModel):
    id: str
    prompt_id: str
    version: int
    notes: str
    created_at: Timestamp
    variables: list[str]


class VersionDetail(ResponseModel):
    id: str
    prompt_id: str
    version: int
    system: str | None
    prompt: str
    notes: str
    settings: PromptSettings
    variables: list[VariableInfoOut]
    created_at: Timestamp


class PromptSummary(ResponseModel):
    id: str
    name: str
    description: str
    tags: list[str]
    archived: bool
    created_at: Timestamp
    updated_at: Timestamp
    version_count: int
    latest_version: VersionSummary


class PromptDetail(ResponseModel):
    id: str
    name: str
    description: str
    tags: list[str]
    archived: bool
    created_at: Timestamp
    updated_at: Timestamp
    version_count: int
    latest_version: VersionDetail


class DiffLine(ResponseModel):
    op: Literal["equal", "insert", "delete"]
    old_line: int | None
    new_line: int | None
    text: str


class TextDiff(ResponseModel):
    changed: bool
    added: int
    removed: int
    unified: str
    lines: list[DiffLine]


class VersionDiff(ResponseModel):
    prompt_id: str
    from_version: int
    to_version: int
    system: TextDiff
    prompt: TextDiff
    settings_changed: bool
    settings_from: PromptSettings
    settings_to: PromptSettings
    notes_from: str
    notes_to: str


class TagCount(ResponseModel):
    tag: str
    count: int


class TagsResponse(ResponseModel):
    tags: list[TagCount]


# ---- compare ---------------------------------------------------------------------------------


class CompareVariantInput(RequestModel):
    label: Label60 | None = None
    system: str | None = None
    prompt: str = Field(min_length=1)
    prompt_version_id: RefId | None = None


class CompareRequest(RequestModel):
    variants: list[CompareVariantInput] = Field(min_length=1)
    models: list[ModelId] = Field(min_length=1)
    variables: Variables = Field(default_factory=dict)
    temperature: Temperature | None = None
    max_tokens: MaxTokens | None = None
    thinking: bool = False
    timeout_seconds: float | None = Field(default=None, allow_inf_nan=False)
    save_history: bool = True

    @field_validator("models")
    @classmethod
    def _unique_models(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("models must be unique")
        return value


class CompareVariant(ResponseModel):
    index: int
    label: str
    system: str | None
    prompt: str
    prompt_version_id: str | None


class CompareCellRef(ResponseModel):
    index: int
    variant_index: int
    model: str
    provider: ProviderId


class CompareCell(CompareCellRef):
    variant_label: str
    status: Literal["ok", "error"]
    result: RunResult | None
    error: ErrorBody | None


class CompareSummary(ResponseModel):
    ok_count: int
    error_count: int
    fastest_cell: int | None
    cheapest_cell: int | None


class CompareResult(ResponseModel):
    id: str
    created_at: Timestamp
    variants: list[CompareVariant]
    models: list[str]
    variables: dict[str, str]
    params: RunParams
    cells: list[CompareCell]
    summary: CompareSummary
    warnings: list[str]


class CompareStartEvent(ResponseModel):
    comparison_id: str
    created_at: Timestamp
    cells: list[CompareCellRef]
    warnings: list[str]


# ---- assertions ------------------------------------------------------------------------------

AssertionValue = Annotated[str, StringConstraints(min_length=1, max_length=10_000)]


class _AssertionBase(RequestModel):
    """Assertions are accepted with defaults omitted and always returned normalized."""


class ContainsAssertion(_AssertionBase):
    type: Literal["contains"]
    value: AssertionValue
    case_sensitive: bool = False


class NotContainsAssertion(_AssertionBase):
    type: Literal["not_contains"]
    value: AssertionValue
    case_sensitive: bool = False


class EqualsAssertion(_AssertionBase):
    type: Literal["equals"]
    value: AssertionValue
    case_sensitive: bool = True
    trim: bool = True


class StartsWithAssertion(_AssertionBase):
    type: Literal["starts_with"]
    value: AssertionValue
    case_sensitive: bool = True
    trim: bool = True


class RegexAssertion(_AssertionBase):
    type: Literal["regex"]
    pattern: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    flags: Annotated[str, StringConstraints(pattern=r"^[ims]{0,3}$")] = ""

    @field_validator("flags")
    @classmethod
    def _unique_flags(cls, value: str) -> str:
        if len(set(value)) != len(value):
            raise ValueError("flags must not repeat")
        return "".join(sorted(value))


class MaxCharsAssertion(_AssertionBase):
    type: Literal["max_chars"]
    value: Annotated[int, Field(ge=0)]


class MinCharsAssertion(_AssertionBase):
    type: Literal["min_chars"]
    value: Annotated[int, Field(ge=0)]


class JsonValidAssertion(_AssertionBase):
    type: Literal["json_valid"]


class JsonSchemaAssertion(_AssertionBase):
    model_config = ConfigDict(extra="forbid", serialize_by_alias=True)

    type: Literal["json_schema"]
    schema_: dict[str, Any] = Field(alias="schema")


class LlmJudgeAssertion(_AssertionBase):
    type: Literal["llm_judge"]
    rubric: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    threshold: Annotated[int, Field(ge=1, le=5)] = 4
    judge_model: ModelId | None = None


Assertion = Annotated[
    ContainsAssertion
    | NotContainsAssertion
    | EqualsAssertion
    | StartsWithAssertion
    | RegexAssertion
    | MaxCharsAssertion
    | MinCharsAssertion
    | JsonValidAssertion
    | JsonSchemaAssertion
    | LlmJudgeAssertion,
    Field(discriminator="type"),
]


# ---- test suites -----------------------------------------------------------------------------


class CaseInput(RequestModel):
    name: Name200
    variables: Variables = Field(default_factory=dict)
    assertions: list[Assertion] = Field(min_length=1)


class CaseOut(ResponseModel):
    """A stored test case (``TestCase`` in the wire contract)."""

    id: str
    suite_id: str
    name: str
    variables: dict[str, str]
    assertions: list[Assertion]
    position: int
    created_at: Timestamp
    updated_at: Timestamp


class LastEval(ResponseModel):
    id: str
    status: EvalStatus
    pass_rate: float | None
    created_at: Timestamp


class SuiteSummary(ResponseModel):
    id: str
    name: str
    description: str
    case_count: int
    created_at: Timestamp
    updated_at: Timestamp
    last_eval: LastEval | None


class SuiteDetail(SuiteSummary):
    cases: list[CaseOut]


class SuiteCreate(RequestModel):
    name: Name120
    description: Description = ""
    cases: list[CaseInput] = Field(default_factory=list)


class SuiteUpdate(RequestModel):
    name: Name120 | None = None
    description: Description | None = None


# ---- evaluations -----------------------------------------------------------------------------


class AssertionResult(ResponseModel):
    type: str
    passed: bool
    score: int | None
    detail: str
    error: str | None


class EvalCreate(RequestModel):
    suite_id: RefId
    prompt_version_id: RefId | None = None
    system: str | None = None
    prompt: Annotated[str, Field(min_length=1)] | None = None
    models: list[ModelId] = Field(min_length=1)
    temperature: Temperature | None = None
    max_tokens: MaxTokens | None = None
    thinking: bool = False
    judge_model: ModelId | None = None

    @field_validator("models")
    @classmethod
    def _unique_models(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("models must be unique")
        return value


class EvalProgress(ResponseModel):
    completed: int
    total: int


class EvalRunSummary(ResponseModel):
    id: str
    suite_id: str | None
    suite_name: str
    prompt_id: str | None
    prompt_version_id: str | None
    prompt_label: str
    models: list[str]
    status: EvalStatus
    progress: EvalProgress
    passed: int
    failed: int
    errored: int
    pass_rate: float | None
    created_at: Timestamp
    started_at: Timestamp | None
    finished_at: Timestamp | None
    error: ErrorBody | None


class EvalCaseSnapshot(ResponseModel):
    index: int
    case_id: str | None
    name: str
    variables: dict[str, str]
    assertions: list[Assertion]


class EvalResult(ResponseModel):
    id: str
    case_index: int
    case_id: str | None
    case_name: str
    model: str
    provider: ProviderId
    status: CaseResultStatus
    output: str | None
    assertions: list[AssertionResult]
    score: float | None
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    error: ErrorBody | None


class EvalModelSummary(ResponseModel):
    model: str
    provider: ProviderId
    passed: int
    failed: int
    errored: int
    pending: int
    pass_rate: float | None
    avg_latency_ms: float | None
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float | None


class EvalRunDetail(EvalRunSummary):
    system: str | None
    prompt: str
    params: RunParams
    judge_model: str
    cases: list[EvalCaseSnapshot]
    results: list[EvalResult]
    per_model: list[EvalModelSummary]


# ---- history ---------------------------------------------------------------------------------


class HistorySummary(ResponseModel):
    id: str
    created_at: Timestamp
    source: Literal["run", "compare"]
    group_id: str | None
    model: str
    provider: ProviderId
    status: HistoryStatus
    prompt_preview: str
    output_preview: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    cost_usd: float | None
    finish_reason: FinishReasonValue | None
    error_code: str | None
    prompt_version_id: str | None


class HistoryDetail(HistorySummary):
    system_template: str | None
    prompt_template: str
    variables: dict[str, str]
    rendered_system: str | None
    rendered_prompt: str
    params: RunParams
    output: str
    thinking: str | None
    error_message: str | None
    ttft_ms: int | None
    request_id: str | None
    warnings: list[str]


class DeletedCount(ResponseModel):
    deleted: int


# ---- export / import -------------------------------------------------------------------------


class ExportVersion(RequestModel):
    id: RefId
    version: Annotated[int, Field(ge=1, le=MAX_STORED_INT)]
    system: str | None = None
    prompt: str = Field(min_length=1)
    notes: Notes = ""
    settings: PromptSettings = Field(default_factory=PromptSettings)
    created_at: Timestamp


class ExportPrompt(RequestModel):
    id: RefId
    name: Name120
    description: Description = ""
    tags: list[str] = Field(default_factory=list)
    archived: bool = False
    created_at: Timestamp
    updated_at: Timestamp
    versions: list[ExportVersion] = Field(min_length=1)

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str]) -> list[str]:
        return normalize_tags(value)


class ExportCase(RequestModel):
    id: RefId
    name: Name200
    variables: Variables = Field(default_factory=dict)
    assertions: list[Assertion] = Field(min_length=1)
    position: StoredCount = 0
    created_at: Timestamp
    updated_at: Timestamp


class ExportSuite(RequestModel):
    id: RefId
    name: Name120
    description: Description = ""
    created_at: Timestamp
    updated_at: Timestamp
    cases: list[ExportCase] = Field(default_factory=list)


class ImportRunParams(RequestModel):
    """``RunParams`` of an imported history entry, checked like a run request.

    Rejects NaN and infinite temperatures (they would break JSON export) and unknown keys.
    """

    temperature: Temperature | None
    max_tokens: Annotated[int, Field(ge=1, le=MAX_STORED_INT)]
    thinking: bool


class ExportHistory(RequestModel):
    """A history entry inside an export document (``HistoryDetail`` shape)."""

    id: RefId
    created_at: Timestamp
    source: Literal["run", "compare"]
    group_id: RefId | None = None
    model: ModelId
    provider: ProviderId
    status: HistoryStatus
    prompt_preview: str = ""
    output_preview: str = ""
    input_tokens: StoredCount | None = None
    output_tokens: StoredCount | None = None
    latency_ms: StoredCount | None = None
    cost_usd: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    finish_reason: FinishReasonValue | None = None
    error_code: Annotated[str, StringConstraints(max_length=64)] | None = None
    prompt_version_id: RefId | None = None
    system_template: str | None = None
    prompt_template: str
    variables: dict[str, str] = Field(default_factory=dict)
    rendered_system: str | None = None
    rendered_prompt: str
    params: ImportRunParams
    output: str = ""
    thinking: str | None = None
    error_message: Annotated[str, StringConstraints(max_length=500)] | None = None
    ttft_ms: StoredCount | None = None
    request_id: Annotated[str, StringConstraints(max_length=128)] | None = None
    warnings: list[str] = Field(default_factory=list)


class ExportDocument(ResponseModel):
    format: Literal["prompt-studio-export"] = "prompt-studio-export"
    format_version: Literal[1] = 1
    exported_at: Timestamp
    app_version: str
    prompts: list[dict[str, Any]]
    suites: list[dict[str, Any]]
    history: list[dict[str, Any]]


class ImportDocument(RequestModel):
    format: Literal["prompt-studio-export"]
    format_version: Literal[1]
    exported_at: Timestamp | None = None
    app_version: str | None = None
    prompts: list[ExportPrompt] = Field(default_factory=list)
    suites: list[ExportSuite] = Field(default_factory=list)
    history: list[ExportHistory] = Field(default_factory=list)


class ImportCounts(ResponseModel):
    created: int = 0
    updated: int = 0
    skipped: int = 0
    renamed: int = 0


class HistoryImportCount(ResponseModel):
    created: int = 0


class ImportResult(ResponseModel):
    prompts: ImportCounts
    suites: ImportCounts
    history: HistoryImportCount
    warnings: list[str]


# ---- pagination ------------------------------------------------------------------------------


class PromptPage(ResponseModel):
    items: list[PromptSummary]
    total: int
    limit: int
    offset: int


class VersionPage(ResponseModel):
    items: list[VersionSummary]
    total: int
    limit: int
    offset: int


class SuitePage(ResponseModel):
    items: list[SuiteSummary]
    total: int
    limit: int
    offset: int


class EvalPage(ResponseModel):
    items: list[EvalRunSummary]
    total: int
    limit: int
    offset: int


class HistoryPage(ResponseModel):
    items: list[HistorySummary]
    total: int
    limit: int
    offset: int
