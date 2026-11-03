"""Evaluations: assertion checks, the JSON-schema subset, the LLM judge and the executor.

An evaluation runs every case of a suite against every selected model in a background task.
Each (case, model) result row is updated in its own short transaction together with the run
counters, so progress is visible while the run is still going.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from typing import Any

import anyio
import regex
from pydantic import TypeAdapter
from sqlalchemy import func, select, update

from app.db import new_id, utcnow
from app.errors import (
    AppError,
    field_error,
    invalid_assertion,
    limit_exceeded,
    missing_variables,
    not_found,
    provider_app_error,
    unknown_model,
)
from app.models import EvalResultRow, EvalRun, Prompt, PromptVersion, TestCase, TestSuite
from app.providers.base import GenerationRequest, ModelSpec, ProviderError
from app.providers.catalog import compute_cost, effective_max_output_tokens
from app.schemas import (
    Assertion,
    AssertionResult,
    ErrorBody,
    EvalCaseSnapshot,
    EvalCreate,
    EvalModelSummary,
    EvalProgress,
    EvalResult,
    EvalRunDetail,
    EvalRunSummary,
    JsonSchemaAssertion,
    LlmJudgeAssertion,
    RegexAssertion,
    RunParams,
)
from app.services import templating
from app.services.common import call_generate, effective_params, resolve_max_tokens, resolve_models
from app.services.validation import check_max_tokens, check_rendered_length, check_template
from app.state import AppState

logger = logging.getLogger(__name__)

# ---- LLM judge prompts -----------------------------------------------------------------------

JUDGE_SYSTEM_PROMPT = (
    "You are an impartial evaluator. Grade the response against the rubric on a 1-5 integer "
    "scale (1 = fails completely, 5 = fully satisfies the rubric). Respond with only a JSON "
    'object: {"score": <integer 1-5>, "reason": "<one sentence>"}.'
)
JUDGE_UNPARSEABLE = "The judge returned an unparseable score."
REGEX_TIMEOUT = "Regex evaluation timed out."
REGEX_TIMEOUT_SECONDS = 1.0
INTERRUPTED_MESSAGE = "The evaluation was interrupted by a server restart."
INTERNAL_ERROR_MESSAGE = "An unexpected error occurred."
AD_HOC_LABEL = "Ad-hoc prompt"
DETAIL_MAX = 500
QUOTE_MAX = 80

ACTIVE_STATUSES = ("queued", "running")

_ASSERTIONS = TypeAdapter(list[Assertion])


def judge_user_prompt(rubric: str, rendered_prompt: str, output: str) -> str:
    return (
        f"<rubric>\n{rubric}\n</rubric>\n\n<input>\n{rendered_prompt}\n</input>\n\n"
        f"<output>\n{output}\n</output>"
    )


# ---- helpers ---------------------------------------------------------------------------------


def strip_fences(text: str) -> str:
    """Remove a surrounding Markdown code fence (```json ... ```), if any."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def _quote(value: str) -> str:
    shortened = value if len(value) <= QUOTE_MAX else value[: QUOTE_MAX - 1] + "…"
    return json.dumps(shortened, ensure_ascii=False)


def _detail(text: str) -> str:
    return text if len(text) <= DETAIL_MAX else text[: DETAIL_MAX - 1] + "…"


def _regex_flags(flags: str) -> int:
    value = 0
    if "i" in flags:
        value |= regex.IGNORECASE
    if "m" in flags:
        value |= regex.MULTILINE
    if "s" in flags:
        value |= regex.DOTALL
    return value


def normalize_assertions(assertions: Sequence[Any]) -> list[dict[str, Any]]:
    """Assertions as stored and returned: every field present."""
    return [
        assertion.model_dump(mode="json", by_alias=True)
        for assertion in _ASSERTIONS.validate_python(list(assertions))
    ]


# ---- JSON-schema subset ----------------------------------------------------------------------

SCHEMA_KEYWORDS = frozenset(
    {
        "type", "properties", "required", "additionalProperties", "items", "minItems",
        "maxItems", "enum", "const", "minLength", "maxLength", "pattern", "minimum", "maximum",
        "exclusiveMinimum", "exclusiveMaximum",
    }
)  # fmt: skip
SCHEMA_ANNOTATIONS = frozenset({"$schema", "title", "description", "default", "examples"})
SCHEMA_TYPES = frozenset({"object", "array", "string", "number", "integer", "boolean", "null"})
SCHEMA_MAX_BYTES = 10_000
SCHEMA_MAX_DEPTH = 10
JSON_MAX_NESTING = 64
MAX_SCHEMA_ERRORS = 5


class SchemaDefinitionError(ValueError):
    """A schema uses something outside the supported subset."""


def _json_depth(value: Any, depth: int = 1) -> int:
    if depth > JSON_MAX_NESTING:
        return depth
    if isinstance(value, dict):
        return max([depth, *(_json_depth(v, depth + 1) for v in value.values())])
    if isinstance(value, list):
        return max([depth, *(_json_depth(v, depth + 1) for v in value)])
    return depth


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def check_schema(schema: Any) -> None:
    """Raise :class:`SchemaDefinitionError` unless ``schema`` fits the supported subset."""
    try:
        encoded = json.dumps(schema, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise SchemaDefinitionError("schema must be plain JSON") from exc
    if len(encoded.encode("utf-8")) > SCHEMA_MAX_BYTES:
        raise SchemaDefinitionError(f"schema is larger than {SCHEMA_MAX_BYTES} bytes")
    if _json_depth(schema) > JSON_MAX_NESTING:
        raise SchemaDefinitionError("schema is nested too deeply")
    _check_subschema(schema, 1, "$")


def _check_subschema(schema: Any, depth: int, path: str) -> None:
    if depth > SCHEMA_MAX_DEPTH:
        raise SchemaDefinitionError(f"schema nesting is deeper than {SCHEMA_MAX_DEPTH} levels")
    if not isinstance(schema, dict):
        raise SchemaDefinitionError(f"{path}: a schema must be an object")
    for key, value in schema.items():
        if key in SCHEMA_ANNOTATIONS:
            continue
        if key not in SCHEMA_KEYWORDS:
            raise SchemaDefinitionError(f"{path}: unsupported keyword {key!r}")
        _check_keyword(key, value, depth, path)


def _check_keyword(key: str, value: Any, depth: int, path: str) -> None:
    if key == "type":
        names = [value] if isinstance(value, str) else value
        if not isinstance(names, list) or not names:
            raise SchemaDefinitionError(f"{path}: 'type' must be a type name or a list of them")
        for name in names:
            if name not in SCHEMA_TYPES:
                raise SchemaDefinitionError(f"{path}: unknown type {name!r}")
    elif key == "properties":
        if not isinstance(value, dict):
            raise SchemaDefinitionError(f"{path}: 'properties' must be an object")
        for name, sub in value.items():
            _check_subschema(sub, depth + 1, child_path(path, name))
    elif key == "required":
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise SchemaDefinitionError(f"{path}: 'required' must be a list of strings")
    elif key == "additionalProperties":
        if not isinstance(value, bool):
            raise SchemaDefinitionError(f"{path}: 'additionalProperties' must be a boolean")
    elif key == "items":
        _check_subschema(value, depth + 1, f"{path}[*]")
    elif key in {"minItems", "maxItems", "minLength", "maxLength"}:
        if not _is_count(value):
            raise SchemaDefinitionError(f"{path}: {key!r} must be a non-negative integer")
    elif key == "enum":
        if not isinstance(value, list) or not value:
            raise SchemaDefinitionError(f"{path}: 'enum' must be a non-empty list")
    elif key == "pattern":
        if not isinstance(value, str):
            raise SchemaDefinitionError(f"{path}: 'pattern' must be a string")
        try:
            regex.compile(value)
        except regex.error as exc:
            raise SchemaDefinitionError(f"{path}: invalid pattern: {exc}") from exc
    elif key in {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"}:
        if not _is_number(value):
            raise SchemaDefinitionError(f"{path}: {key!r} must be a number")
    # "const" accepts any JSON value.


def child_path(path: str, key: str) -> str:
    if regex.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        return f"{path}.{key}"
    return f"{path}[{json.dumps(key, ensure_ascii=False)}]"


def json_equal(a: Any, b: Any) -> bool:
    """JSON value equality: ``1 == 1.0``, but booleans never equal numbers."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if _is_number(a) and _is_number(b):
        return bool(a == b)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def _matches_type(value: Any, name: str) -> bool:
    match name:
        case "object":
            return isinstance(value, dict)
        case "array":
            return isinstance(value, list)
        case "string":
            return isinstance(value, str)
        case "number":
            return _is_number(value)
        case "integer":
            return (isinstance(value, int) and not isinstance(value, bool)) or (
                isinstance(value, float) and value.is_integer()
            )
        case "boolean":
            return isinstance(value, bool)
        case _:
            return value is None


class _RegexTimeoutError(Exception):
    pass


class RegexBudget:
    """One time budget shared by every regex search made for a single assertion.

    A ``json_schema`` assertion can apply its ``pattern`` to hundreds of array items; a fresh
    timeout per search would let one assertion use minutes of CPU, so each search only gets the
    time that is left.
    """

    def __init__(self, seconds: float = REGEX_TIMEOUT_SECONDS) -> None:
        self._deadline = time.monotonic() + seconds

    def search(self, pattern: str, text: str, flags: int = 0) -> bool:
        """``regex.search(...) is not None``; raises ``_RegexTimeoutError`` once time is up."""
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise _RegexTimeoutError
        try:
            return regex.search(pattern, text, flags, timeout=remaining) is not None
        except TimeoutError as exc:
            raise _RegexTimeoutError from exc


def validate_instance(
    schema: dict[str, Any],
    value: Any,
    path: str,
    errors: list[str],
    budget: RegexBudget | None = None,
) -> None:
    """Append up to five human-readable violations of ``schema`` by ``value``.

    Every ``pattern`` check shares ``budget`` (a new 1 s budget when omitted); running out of it
    raises ``_RegexTimeoutError``.
    """
    if budget is None:
        budget = RegexBudget()
    if len(errors) >= MAX_SCHEMA_ERRORS:
        return
    if "type" in schema:
        names = [schema["type"]] if isinstance(schema["type"], str) else list(schema["type"])
        if not any(_matches_type(value, name) for name in names):
            errors.append(f"{path}: expected {' or '.join(names)}")
            return
    if "enum" in schema and not any(json_equal(value, item) for item in schema["enum"]):
        errors.append(f"{path}: value is not one of the allowed values")
    if "const" in schema and not json_equal(value, schema["const"]):
        errors.append(f"{path}: value does not equal the expected constant")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: expected at least {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: expected at most {schema['maxLength']} characters")
        if "pattern" in schema and not budget.search(schema["pattern"], value):
            errors.append(f"{path}: does not match pattern {_quote(schema['pattern'])}")
    if _is_number(value):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: expected a value >= {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: expected a value <= {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: expected a value > {schema['exclusiveMinimum']}")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            errors.append(f"{path}: expected a value < {schema['exclusiveMaximum']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: expected at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: expected at most {schema['maxItems']} items")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                validate_instance(schema["items"], item, f"{path}[{index}]", errors, budget)
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path}: missing required property {_quote(name)}")
        properties: dict[str, Any] = schema.get("properties", {})
        for name, sub in properties.items():
            if name in value:
                validate_instance(sub, value[name], child_path(path, name), errors, budget)
        if schema.get("additionalProperties") is False:
            for name in value:
                if name not in properties:
                    errors.append(f"{path}: unexpected property {_quote(name)}")
    del errors[MAX_SCHEMA_ERRORS:]


# ---- assertion validation (save time) --------------------------------------------------------


def validate_case_assertions(
    state: AppState,
    assertions: Sequence[Any],
    *,
    case_index: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Semantic checks: assertion count, regex compiles, schema subset, judge model in catalog."""
    settings = state.settings
    if len(assertions) > settings.max_assertions_per_case:
        raise limit_exceeded("max_assertions_per_case", settings.max_assertions_per_case)
    where: dict[str, Any] = dict(extra or {})
    if case_index is not None:
        where["case_index"] = case_index
    for index, assertion in enumerate(assertions):
        if isinstance(assertion, RegexAssertion):
            try:
                regex.compile(assertion.pattern, _regex_flags(assertion.flags))
            except regex.error as exc:
                raise invalid_assertion(
                    f"Invalid regular expression: {exc}", index, **where
                ) from None
        elif isinstance(assertion, JsonSchemaAssertion):
            try:
                check_schema(assertion.schema_)
            except SchemaDefinitionError as exc:
                raise invalid_assertion(f"Invalid JSON schema: {exc}", index, **where) from None
        elif (
            isinstance(assertion, LlmJudgeAssertion)
            and assertion.judge_model is not None
            and state.registry.get_model(assertion.judge_model) is None
        ):
            raise invalid_assertion(f"Unknown judge model: {assertion.judge_model}", index, **where)


# ---- assertion evaluation --------------------------------------------------------------------


def _result(
    type_: str, passed: bool, detail: str, *, score: int | None = None, error: str | None = None
) -> AssertionResult:
    return AssertionResult(
        type=type_, passed=passed, score=score, detail=_detail(detail), error=error
    )


def _parse_json(output: str) -> tuple[Any, str | None]:
    try:
        return json.loads(strip_fences(output)), None
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}."
    except RecursionError:
        return None, "Invalid JSON: the document is nested too deeply."


def evaluate_static(assertion: Any, output: str) -> AssertionResult:
    """Evaluate a non-judge assertion against the model output."""
    kind: str = assertion.type
    if kind in {"contains", "not_contains"}:
        haystack, needle = output, assertion.value
        if not assertion.case_sensitive:
            haystack, needle = haystack.casefold(), needle.casefold()
        found = needle in haystack
        message = (
            f"Output contains {_quote(assertion.value)}."
            if found
            else f"Output does not contain {_quote(assertion.value)}."
        )
        return _result(kind, found if kind == "contains" else not found, message)
    if kind in {"equals", "starts_with"}:
        value = assertion.value
        if kind == "equals":
            text, expected = (output.strip(), value.strip()) if assertion.trim else (output, value)
        else:
            text, expected = (output.lstrip() if assertion.trim else output), value
        if not assertion.case_sensitive:
            text, expected = text.casefold(), expected.casefold()
        if kind == "equals":
            ok = text == expected
            message = (
                "Output equals the expected value."
                if ok
                else "Output does not equal the expected value."
            )
        else:
            ok = text.startswith(expected)
            message = (
                f"Output starts with {_quote(value)}."
                if ok
                else f"Output does not start with {_quote(value)}."
            )
        return _result(kind, ok, message)
    if kind == "regex":
        try:
            ok = RegexBudget().search(assertion.pattern, output, _regex_flags(assertion.flags))
        except _RegexTimeoutError:
            return _result(kind, False, REGEX_TIMEOUT, error=REGEX_TIMEOUT)
        shown = _quote(assertion.pattern)
        return _result(
            kind, ok, f"Output matches {shown}." if ok else f"Output does not match {shown}."
        )
    if kind == "max_chars":
        length = len(output)
        return _result(
            kind,
            length <= assertion.value,
            f"Output has {length} characters (max {assertion.value}).",
        )
    if kind == "min_chars":
        length = len(output)
        return _result(
            kind,
            length >= assertion.value,
            f"Output has {length} characters (min {assertion.value}).",
        )
    parsed, problem = _parse_json(output)
    if problem is not None:
        return _result(kind, False, problem)
    if kind == "json_valid":
        return _result(kind, True, "Output is valid JSON.")
    errors: list[str] = []
    try:
        validate_instance(assertion.schema_, parsed, "$", errors)
    except _RegexTimeoutError:
        return _result(kind, False, REGEX_TIMEOUT, error=REGEX_TIMEOUT)
    except RecursionError:
        return _result(kind, False, "Output is nested too deeply to validate.")
    if errors:
        return _result(kind, False, "; ".join(errors[:MAX_SCHEMA_ERRORS]))
    return _result(kind, True, "Output matches the JSON schema.")


def parse_judge_reply(text: str) -> tuple[int, str] | None:
    """``(score, reason)`` from a judge reply, or ``None`` when the score is unusable."""
    body = strip_fences(text)
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        data = json.loads(body[start : end + 1])
    except (json.JSONDecodeError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get("score")
    score: int | None = None
    if isinstance(raw, bool):
        score = None
    elif isinstance(raw, int):
        score = raw
    elif isinstance(raw, float) and raw.is_integer():
        score = int(raw)
    elif isinstance(raw, str):
        try:
            number = float(raw.strip())
        except ValueError:
            number = math.nan
        if number.is_integer():
            score = int(number)
    if score is None or not 1 <= score <= 5:
        return None
    reason = data.get("reason")
    return score, reason if isinstance(reason, str) else ""


async def judge(
    state: AppState,
    assertion: LlmJudgeAssertion,
    judge_spec: ModelSpec,
    rendered_prompt: str,
    output: str,
) -> AssertionResult:
    """Ask the judge model for a 1-5 score and compare it with the threshold."""
    settings = state.settings
    request = GenerationRequest(
        model=judge_spec,
        system=JUDGE_SYSTEM_PROMPT,
        prompt=judge_user_prompt(assertion.rubric, rendered_prompt, output),
        temperature=None,
        max_tokens=min(
            settings.judge_max_tokens, effective_max_output_tokens(judge_spec, settings)
        ),
        thinking=False,
        timeout_s=settings.request_timeout_seconds,
    )
    try:
        reply = await call_generate(state, judge_spec, request)
    except ProviderError as error:
        code = provider_app_error(error).code
        return _result(
            "llm_judge", False, "The judge call failed.", error=f"Judge call failed: {code}"
        )
    parsed = parse_judge_reply(reply.text)
    if parsed is None:
        return _result("llm_judge", False, JUDGE_UNPARSEABLE, error=JUDGE_UNPARSEABLE)
    score, reason = parsed
    passed = score >= assertion.threshold
    detail = f"Judge score {score}/5 (threshold {assertion.threshold})"
    if reason:
        detail += f": {reason}"
    return _result("llm_judge", passed, detail, score=score)


async def evaluate_assertions(
    state: AppState,
    assertions: Sequence[Any],
    output: str,
    rendered_prompt: str,
    default_judge: str,
) -> list[AssertionResult]:
    """Evaluate assertions in order (regex/schema work runs in a thread)."""
    results: list[AssertionResult] = []
    for assertion in assertions:
        if isinstance(assertion, LlmJudgeAssertion):
            # Judge models were checked (catalog and availability) when the run was created.
            spec = _model_spec(state, assertion.judge_model or default_judge)
            results.append(await judge(state, assertion, spec, rendered_prompt, output))
        elif assertion.type in {"regex", "json_schema"}:
            results.append(await asyncio.to_thread(evaluate_static, assertion, output))
        else:
            results.append(evaluate_static(assertion, output))
    return results


def case_status(results: Sequence[AssertionResult]) -> tuple[str, float]:
    """(status, score) for a case whose generation succeeded."""
    passed = sum(1 for item in results if item.passed)
    score = passed / len(results) if results else 0.0
    if any(item.error is not None for item in results):
        return "error", score
    return ("passed" if passed == len(results) else "failed"), score


# ---- run creation ----------------------------------------------------------------------------


@dataclass(frozen=True)
class _PromptSource:
    system: str | None
    prompt: str
    prompt_id: str | None
    prompt_version_id: str | None
    label: str


async def _prompt_source(state: AppState, req: EvalCreate) -> _PromptSource:
    if (req.prompt_version_id is None) == (req.prompt is None):
        raise field_error(["body"], "Provide exactly one of prompt_version_id or prompt.")
    if req.prompt_version_id is not None:
        async with state.db.read() as session:
            version = await session.get(PromptVersion, req.prompt_version_id)
            prompt = await session.get(Prompt, version.prompt_id) if version else None
        if version is None or prompt is None:
            raise not_found("prompt_version")
        return _PromptSource(
            version.system,
            version.prompt,
            prompt.id,
            version.id,
            f"{prompt.name} v{version.version}",
        )
    prompt = req.prompt or ""
    check_template(state.settings, system=req.system, prompt=prompt)
    return _PromptSource(req.system, prompt, None, None, AD_HOC_LABEL)


def eval_call_count(cases: Sequence[TestCase], model_count: int) -> int:
    """Provider calls one evaluation makes: per case and model, one generation call plus one
    judge call for each ``llm_judge`` assertion. This is what ``MAX_EVAL_CALLS`` bounds.
    """
    judge_calls = sum(
        1
        for case in cases
        for assertion in case.assertions
        if isinstance(assertion, dict) and assertion.get("type") == "llm_judge"
    )
    return (len(cases) + judge_calls) * model_count


def _judge_id(state: AppState, req: EvalCreate) -> str:
    """Default judge: ``request.judge_model ?? JUDGE_MODEL ?? effective default model``."""
    if req.judge_model is not None:
        return req.judge_model
    return state.settings.judge_model or state.registry.effective_default_model().id


async def create_eval(state: AppState, req: EvalCreate) -> str:
    """Validate and store the run with pending results; returns the run id.

    The caller starts it with :func:`start_eval`.
    """
    settings = state.settings
    async with state.db.read() as session:
        suite = await session.get(TestSuite, req.suite_id)
        if suite is None:
            raise not_found("suite")
        cases = list(
            await session.scalars(
                select(TestCase).where(TestCase.suite_id == suite.id).order_by(TestCase.position)
            )
        )
    if not cases:
        raise AppError(422, "empty_suite", "The test suite has no cases.")
    source = await _prompt_source(state, req)
    if len(req.models) > settings.max_eval_models:
        raise limit_exceeded("max_eval_models", settings.max_eval_models)
    specs = resolve_models(state, req.models)
    calls = eval_call_count(cases, len(specs))
    if calls > settings.max_eval_calls:
        raise limit_exceeded(
            "max_eval_calls",
            settings.max_eval_calls,
            f"The evaluation needs {calls} provider calls (cases x models, plus one judge call "
            f"per LLM judge assertion and model); the limit is {settings.max_eval_calls}.",
        )
    check_max_tokens(settings, req.max_tokens)
    max_tokens = resolve_max_tokens(specs, settings, req.max_tokens)

    failing: list[dict[str, Any]] = []
    for case in cases:
        rendered = templating.render(source.system, source.prompt, case.variables)
        if rendered.missing:
            failing.append(
                {"case_id": case.id, "case_name": case.name, "missing": list(rendered.missing)}
            )
        else:
            check_rendered_length(
                settings, templating.normalize_system(rendered.system), rendered.prompt
            )
    if failing:
        union = sorted({name for item in failing for name in item["missing"]})
        raise missing_variables(union, cases=failing)

    default_judge = _judge_id(state, req)
    snapshots: list[dict[str, Any]] = []
    for case_index, case in enumerate(cases):
        parsed = _ASSERTIONS.validate_python(case.assertions)
        for assertion_index, assertion in enumerate(parsed):
            if not isinstance(assertion, LlmJudgeAssertion):
                continue
            judge_id = assertion.judge_model or default_judge
            judge_spec = state.registry.get_model(judge_id)
            if judge_spec is None:
                raise invalid_assertion(
                    f"Unknown judge model: {judge_id}", assertion_index, case_index=case_index
                )
            if not state.registry.is_available(judge_spec):
                raise invalid_assertion(
                    f"The judge model {judge_id} is not available: its provider is not configured.",
                    assertion_index,
                    case_index=case_index,
                )
        snapshots.append(
            {
                "index": case_index,
                "case_id": case.id,
                "name": case.name,
                "variables": dict(case.variables),
                "assertions": [item.model_dump(mode="json", by_alias=True) for item in parsed],
            }
        )

    # A request-level judge used by no assertion still has to be a real model, since it is
    # stored as the run's judge.
    if state.registry.get_model(default_judge) is None:
        raise unknown_model(default_judge)

    run_id = new_id()
    params = {"temperature": req.temperature, "max_tokens": max_tokens, "thinking": req.thinking}
    async with state.db.write() as session:
        session.add(
            EvalRun(
                id=run_id,
                suite_id=suite.id,
                suite_name=suite.name,
                prompt_id=source.prompt_id,
                prompt_version_id=source.prompt_version_id,
                prompt_label=source.label,
                system=source.system,
                prompt=source.prompt,
                models=[spec.id for spec in specs],
                params=params,
                judge_model=default_judge,
                cases_snapshot=snapshots,
                status="queued",
                total=len(cases) * len(specs),
            )
        )
        for snapshot in snapshots:
            for spec in specs:
                session.add(
                    EvalResultRow(
                        eval_run_id=run_id,
                        case_index=snapshot["index"],
                        case_id=snapshot["case_id"],
                        case_name=snapshot["name"],
                        model=spec.id,
                        provider=spec.provider.value,
                        status="pending",
                    )
                )
    return run_id


# ---- execution -------------------------------------------------------------------------------


def start_eval(state: AppState, run_id: str) -> None:
    task = asyncio.create_task(execute_eval(state, run_id), name=f"eval-{run_id}")
    state.eval_tasks[run_id] = task


async def _shielded(awaitable: Awaitable[None]) -> None:
    """Finish a database write even if the caller is cancelled meanwhile."""
    task = asyncio.ensure_future(awaitable)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        with anyio.CancelScope(shield=True):
            await asyncio.gather(task, return_exceptions=True)
        raise


async def _mark_run(state: AppState, run_id: str, **values: Any) -> None:
    async with state.db.write() as session:
        await session.execute(
            update(EvalRun)
            .where(EvalRun.id == run_id, EvalRun.status.in_(ACTIVE_STATUSES))
            .values(**values)
        )


async def execute_eval(state: AppState, run_id: str) -> None:
    """Background task: run every pending (case, model) job, then mark the run finished."""
    try:
        async with state.db.write() as session:
            run = await session.get(EvalRun, run_id)
            if run is None or run.status not in ACTIVE_STATUSES:
                return
            run.status = "running"
            run.started_at = utcnow()
        async with state.db.read() as session:
            rows = list(
                await session.scalars(
                    select(EvalResultRow)
                    .where(EvalResultRow.eval_run_id == run_id, EvalResultRow.status == "pending")
                    .order_by(EvalResultRow.case_index)
                )
            )
        cases = {item["index"]: item for item in run.cases_snapshot}
        specs = {model: _model_spec(state, model) for model in run.models}
        params = RunParams(**run.params)
        semaphore = asyncio.Semaphore(state.settings.eval_concurrency)
        async with asyncio.TaskGroup() as group:
            for row in rows:
                group.create_task(
                    _run_job(
                        state, run, row, specs[row.model], cases[row.case_index], params, semaphore
                    )
                )
        await _mark_run(state, run_id, status="completed", finished_at=utcnow())
    except asyncio.CancelledError:
        with anyio.CancelScope(shield=True):
            await _mark_run(state, run_id, status="cancelled", finished_at=utcnow())
        raise
    except Exception:
        logger.exception("Evaluation %s failed", run_id)
        with anyio.CancelScope(shield=True):
            await _mark_run(
                state,
                run_id,
                status="failed",
                finished_at=utcnow(),
                error_code="internal_error",
                error_message=INTERNAL_ERROR_MESSAGE,
            )
    finally:
        state.eval_tasks.pop(run_id, None)


def _model_spec(state: AppState, model: str) -> ModelSpec:
    spec = state.registry.get_model(model)
    if spec is None:
        raise LookupError(f"model {model!r} is no longer in the catalog")
    return spec


@dataclass
class _JobOutcome:
    status: str
    output: str | None = None
    assertions: list[dict[str, Any]] | None = None
    score: float | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    error_code: str | None = None
    error_message: str | None = None


async def _job_outcome(
    state: AppState, run: EvalRun, spec: ModelSpec, case: dict[str, Any], params: RunParams
) -> _JobOutcome:
    # Variables were checked when the run was created against this same snapshot, so the
    # strict render cannot report missing names here.
    rendered = templating.render(run.system, run.prompt, case["variables"])
    effective = effective_params(
        spec, temperature=params.temperature, max_tokens=params.max_tokens, thinking=params.thinking
    )
    request = GenerationRequest(
        model=spec,
        system=templating.normalize_system(rendered.system),
        prompt=rendered.prompt,
        temperature=effective.temperature,
        max_tokens=effective.max_tokens,
        thinking=effective.thinking,
        timeout_s=state.settings.request_timeout_seconds,
    )
    try:
        generated = await call_generate(state, spec, request)
    except ProviderError as error:
        app_error = provider_app_error(error)
        return _JobOutcome("error", error_code=app_error.code, error_message=app_error.message)
    assertions = _ASSERTIONS.validate_python(case["assertions"])
    results = await evaluate_assertions(
        state, assertions, generated.text, rendered.prompt, run.judge_model
    )
    status, score = case_status(results)
    return _JobOutcome(
        status,
        output=generated.text,
        assertions=[item.model_dump(mode="json") for item in results],
        score=score,
        latency_ms=generated.latency_ms,
        input_tokens=generated.input_tokens,
        output_tokens=generated.output_tokens,
        cost_usd=compute_cost(spec.pricing, generated.input_tokens, generated.output_tokens),
    )


async def _run_job(
    state: AppState,
    run: EvalRun,
    row: EvalResultRow,
    spec: ModelSpec,
    case: dict[str, Any],
    params: RunParams,
    semaphore: asyncio.Semaphore,
) -> None:
    async with semaphore:
        try:
            outcome = await _job_outcome(state, run, spec, case, params)
        except Exception:
            logger.exception("Evaluation job failed (run %s, case %s)", run.id, row.case_index)
            outcome = _JobOutcome(
                "error", error_code="internal_error", error_message=INTERNAL_ERROR_MESSAGE
            )
    await _shielded(_store_outcome(state, run.id, row.id, outcome))


async def _store_outcome(state: AppState, run_id: str, row_id: str, outcome: _JobOutcome) -> None:
    async with state.db.write() as session:
        row = await session.get(EvalResultRow, row_id)
        if row is None or row.status != "pending":
            return
        row.status = outcome.status
        row.output = outcome.output
        row.assertions = outcome.assertions or []
        row.score = outcome.score
        row.latency_ms = outcome.latency_ms
        row.input_tokens = outcome.input_tokens
        row.output_tokens = outcome.output_tokens
        row.cost_usd = outcome.cost_usd
        row.error_code = outcome.error_code
        row.error_message = outcome.error_message
        row.updated_at = utcnow()
        counter = {"passed": EvalRun.passed, "failed": EvalRun.failed, "error": EvalRun.errored}[
            outcome.status
        ]
        await session.execute(
            update(EvalRun)
            .where(EvalRun.id == run_id)
            .values({EvalRun.completed: EvalRun.completed + 1, counter: counter + 1})
        )


# ---- queries and lifecycle -------------------------------------------------------------------


async def get_run(state: AppState, eval_id: str) -> EvalRun:
    async with state.db.read() as session:
        run = await session.get(EvalRun, eval_id)
    if run is None:
        raise not_found("eval")
    return run


async def cancel_eval(state: AppState, eval_id: str) -> EvalRun:
    run = await get_run(state, eval_id)
    if run.status not in ACTIVE_STATUSES:
        raise AppError(409, "eval_not_running", "The evaluation is not running.")
    task = state.eval_tasks.get(eval_id)
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    await _mark_run(state, eval_id, status="cancelled", finished_at=utcnow())
    run = await get_run(state, eval_id)
    if run.status != "cancelled":
        raise AppError(409, "eval_not_running", "The evaluation is not running.")
    return run


async def delete_eval(state: AppState, eval_id: str) -> None:
    run = await get_run(state, eval_id)
    task = state.eval_tasks.get(run.id)
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    async with state.db.write() as session:
        stored = await session.get(EvalRun, eval_id)
        if stored is not None:
            await session.delete(stored)


async def recover_interrupted(state: AppState) -> int:
    """Runs left queued/running by a previous process become ``failed`` (``interrupted``)."""
    async with state.db.write() as session:
        result = await session.execute(
            update(EvalRun)
            .where(EvalRun.status.in_(ACTIVE_STATUSES))
            .values(
                status="failed",
                error_code="interrupted",
                error_message=INTERRUPTED_MESSAGE,
                finished_at=utcnow(),
            )
        )
        return int(result.rowcount or 0)


async def shutdown_evals(state: AppState) -> None:
    """Cancel running evaluations (they end ``cancelled``)."""
    tasks = [task for task in state.eval_tasks.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


# ---- responses -------------------------------------------------------------------------------


def _pass_rate(passed: int, completed: int) -> float | None:
    return passed / completed if completed else None


def run_summary(run: EvalRun) -> EvalRunSummary:
    return EvalRunSummary(**_summary_fields(run))


def _summary_fields(run: EvalRun) -> dict[str, Any]:
    error = (
        ErrorBody(code=run.error_code, message=run.error_message or "")
        if run.status == "failed" and run.error_code
        else None
    )
    return {
        "id": run.id,
        "suite_id": run.suite_id,
        "suite_name": run.suite_name,
        "prompt_id": run.prompt_id,
        "prompt_version_id": run.prompt_version_id,
        "prompt_label": run.prompt_label,
        "models": list(run.models),
        "status": run.status,
        "progress": EvalProgress(completed=run.completed, total=run.total),
        "passed": run.passed,
        "failed": run.failed,
        "errored": run.errored,
        "pass_rate": _pass_rate(run.passed, run.completed),
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "error": error,
    }


def _result_out(row: EvalResultRow) -> EvalResult:
    return EvalResult(
        id=row.id,
        case_index=row.case_index,
        case_id=row.case_id,
        case_name=row.case_name,
        model=row.model,
        provider=row.provider,
        status=row.status,
        output=row.output,
        assertions=[AssertionResult(**item) for item in row.assertions or []],
        score=row.score,
        latency_ms=row.latency_ms,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        cost_usd=row.cost_usd,
        error=(
            ErrorBody(code=row.error_code, message=row.error_message or "")
            if row.error_code
            else None
        ),
    )


def _model_summary(model: str, provider: str, rows: list[EvalResultRow]) -> EvalModelSummary:
    passed = sum(1 for row in rows if row.status == "passed")
    failed = sum(1 for row in rows if row.status == "failed")
    errored = sum(1 for row in rows if row.status == "error")
    pending = sum(1 for row in rows if row.status == "pending")
    latencies = [row.latency_ms for row in rows if row.latency_ms is not None]
    costs = [row.cost_usd for row in rows if row.cost_usd is not None]
    return EvalModelSummary(
        model=model,
        provider=provider,
        passed=passed,
        failed=failed,
        errored=errored,
        pending=pending,
        pass_rate=_pass_rate(passed, passed + failed + errored),
        avg_latency_ms=round(sum(latencies) / len(latencies), 1) if latencies else None,
        total_input_tokens=sum(row.input_tokens or 0 for row in rows),
        total_output_tokens=sum(row.output_tokens or 0 for row in rows),
        total_cost_usd=round(sum(costs), 6) if costs else None,
    )


async def run_detail(state: AppState, eval_id: str) -> EvalRunDetail:
    run = await get_run(state, eval_id)
    async with state.db.read() as session:
        rows = list(
            await session.scalars(select(EvalResultRow).where(EvalResultRow.eval_run_id == run.id))
        )
    order = {model: index for index, model in enumerate(run.models)}
    rows.sort(key=lambda row: (row.case_index, order.get(row.model, len(order))))
    per_model = []
    for model in run.models:
        model_rows = [row for row in rows if row.model == model]
        # Every (case, model) pair has a result row, so each model has at least one.
        per_model.append(_model_summary(model, model_rows[0].provider, model_rows))
    return EvalRunDetail(
        **_summary_fields(run),
        system=run.system,
        prompt=run.prompt,
        params=RunParams(**run.params),
        judge_model=run.judge_model,
        cases=[EvalCaseSnapshot(**item) for item in run.cases_snapshot],
        results=[_result_out(row) for row in rows],
        per_model=per_model,
    )


async def list_runs(
    state: AppState,
    *,
    suite_id: str | None,
    prompt_id: str | None,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[EvalRun], int]:
    filters: list[Any] = []
    if suite_id:
        filters.append(EvalRun.suite_id == suite_id)
    if prompt_id:
        filters.append(EvalRun.prompt_id == prompt_id)
    if status:
        filters.append(EvalRun.status == status)
    async with state.db.read() as session:
        total = await session.scalar(select(func.count()).select_from(EvalRun).where(*filters))
        runs = await session.scalars(
            select(EvalRun)
            .where(*filters)
            .order_by(EvalRun.created_at.desc(), EvalRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(runs), int(total or 0)
