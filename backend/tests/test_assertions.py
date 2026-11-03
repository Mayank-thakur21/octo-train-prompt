"""Assertion semantics, the JSON-schema subset and judge reply parsing."""

from __future__ import annotations

import json
import time

import pytest
from pydantic import TypeAdapter

from app.schemas import Assertion
from app.services.evaluation import (
    REGEX_TIMEOUT,
    SchemaDefinitionError,
    case_status,
    check_schema,
    evaluate_static,
    json_equal,
    parse_judge_reply,
    strip_fences,
    validate_instance,
)

ADAPTER = TypeAdapter(Assertion)


def check(spec: dict, output: str):
    return evaluate_static(ADAPTER.validate_python(spec), output)


@pytest.mark.parametrize(
    ("spec", "output", "passed", "detail"),
    [
        ({"type": "contains", "value": "Foo"}, "a foo b", True, 'Output contains "Foo".'),
        (
            {"type": "contains", "value": "Foo", "case_sensitive": True},
            "a foo b",
            False,
            'Output does not contain "Foo".',
        ),
        (
            {"type": "not_contains", "value": "bar"},
            "a foo b",
            True,
            'Output does not contain "bar".',
        ),
        ({"type": "not_contains", "value": "FOO"}, "a foo b", False, 'Output contains "FOO".'),
        (
            {"type": "equals", "value": " Paris "},
            "Paris\n",
            True,
            "Output equals the expected value.",
        ),
        (
            {"type": "equals", "value": "paris"},
            "Paris",
            False,
            "Output does not equal the expected value.",
        ),
        ({"type": "equals", "value": "paris", "case_sensitive": False}, "PARIS", True, None),
        ({"type": "equals", "value": "a", "trim": False}, " a", False, None),
        (
            {"type": "starts_with", "value": "Yes"},
            "  Yes, indeed",
            True,
            'Output starts with "Yes".',
        ),
        ({"type": "starts_with", "value": "Yes", "trim": False}, "  Yes", False, None),
        ({"type": "starts_with", "value": "yes", "case_sensitive": False}, "YES", True, None),
        ({"type": "regex", "pattern": r"^\d+$"}, "123", True, 'Output matches "^\\\\d+$".'),
        ({"type": "regex", "pattern": "^b", "flags": "m"}, "a\nb", True, None),
        ({"type": "regex", "pattern": "A.B", "flags": "is"}, "a\nb", True, None),
        ({"type": "regex", "pattern": "^b"}, "a\nb", False, None),
        ({"type": "max_chars", "value": 3}, "abcd", False, "Output has 4 characters (max 3)."),
        ({"type": "min_chars", "value": 3}, "abcd", True, "Output has 4 characters (min 3)."),
        ({"type": "json_valid"}, '```json\n{"a": 1}\n```', True, "Output is valid JSON."),
        (
            {"type": "json_valid"},
            "nope",
            False,
            "Invalid JSON: Expecting value at line 1 column 1.",
        ),
    ],
)
def test_static_assertions(spec: dict, output: str, passed: bool, detail: str | None) -> None:
    result = check(spec, output)
    assert result.passed is passed
    assert result.type == spec["type"]
    assert result.score is None
    assert result.error is None
    if detail is not None:
        assert result.detail == detail


def test_long_values_are_shortened_in_details() -> None:
    result = check({"type": "contains", "value": "x" * 300}, "y")
    assert len(result.detail) < 120
    assert "…" in result.detail


def test_regex_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.evaluation as evaluation

    def slow(*_args, **_kwargs):
        raise TimeoutError

    monkeypatch.setattr(evaluation.regex, "search", slow)
    result = check({"type": "regex", "pattern": "a"}, "aaa")
    assert result.passed is False
    assert result.error == REGEX_TIMEOUT
    schema = check({"type": "json_schema", "schema": {"type": "string", "pattern": "a"}}, '"a"')
    assert schema.error == REGEX_TIMEOUT


def test_schema_patterns_share_one_regex_budget() -> None:
    # Each item matches only after about 0.6 s of backtracking; with a fresh 1 s timeout per
    # item, 200 items used to take two minutes of CPU and still pass.
    spec = {
        "type": "json_schema",
        "schema": {"type": "array", "items": {"type": "string", "pattern": "(a|aa)+$|!"}},
    }
    output = json.dumps(["a" * 28 + "!"] * 200)
    started = time.perf_counter()
    result = check(spec, output)
    elapsed = time.perf_counter() - started
    assert result.passed is False
    assert result.error == REGEX_TIMEOUT
    assert elapsed < 3.0, f"{elapsed:.2f}s"


def test_regex_budget_stops_once_time_is_up() -> None:
    from app.services.evaluation import RegexBudget, _RegexTimeoutError

    budget = RegexBudget(seconds=0)
    with pytest.raises(_RegexTimeoutError):
        budget.search("a", "a")
    assert RegexBudget().search("b", "abc") is True


SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Person",
    "type": "object",
    "required": ["name", "age"],
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "minLength": 2, "maxLength": 5, "pattern": "^[A-Z]"},
        "age": {"type": "integer", "minimum": 0, "maximum": 150},
        "score": {"type": ["number", "null"], "exclusiveMinimum": 0, "exclusiveMaximum": 1},
        "tags": {"type": "array", "items": {"enum": ["a", "b"]}, "minItems": 1, "maxItems": 2},
        "kind": {"const": "person"},
        "flag": {"type": "boolean"},
        "odd key": {"type": "string"},
    },
}


@pytest.mark.parametrize(
    ("value", "errors"),
    [
        ({"name": "Ada", "age": 36}, []),
        ({"name": "Ada", "age": 36.0, "score": None, "tags": ["a"], "kind": "person"}, []),
        ([], ["$: expected object"]),
        ({"name": "Ada"}, ['$: missing required property "age"']),
        ({"name": "ada", "age": 1}, ['$.name: does not match pattern "^[A-Z]"']),
        ({"name": "A", "age": 1}, ["$.name: expected at least 2 characters"]),
        ({"name": "Abcdef", "age": 1}, ["$.name: expected at most 5 characters"]),
        ({"name": "Ada", "age": 1.5}, ["$.age: expected integer"]),
        ({"name": "Ada", "age": True}, ["$.age: expected integer"]),
        ({"name": "Ada", "age": -1}, ["$.age: expected a value >= 0"]),
        ({"name": "Ada", "age": 200}, ["$.age: expected a value <= 150"]),
        ({"name": "Ada", "age": 1, "score": 0}, ["$.score: expected a value > 0"]),
        ({"name": "Ada", "age": 1, "score": 1}, ["$.score: expected a value < 1"]),
        ({"name": "Ada", "age": 1, "score": True}, ["$.score: expected number or null"]),
        ({"name": "Ada", "age": 1, "tags": []}, ["$.tags: expected at least 1 items"]),
        ({"name": "Ada", "age": 1, "tags": ["a", "b", "a"]}, ["$.tags: expected at most 2 items"]),
        ({"name": "Ada", "age": 1, "tags": ["c"]},
         ["$.tags[0]: value is not one of the allowed values"]),
        ({"name": "Ada", "age": 1, "kind": "robot"},
         ["$.kind: value does not equal the expected constant"]),
        ({"name": "Ada", "age": 1, "flag": 1}, ["$.flag: expected boolean"]),
        ({"name": "Ada", "age": 1, "odd key": 1}, ['$["odd key"]: expected string']),
        ({"name": "Ada", "age": 1, "extra": 1}, ['$: unexpected property "extra"']),
    ],
)  # fmt: skip
def test_schema_validation(value, errors: list[str]) -> None:
    check_schema(SCHEMA)
    found: list[str] = []
    validate_instance(SCHEMA, value, "$", found)
    assert found == errors


def test_schema_errors_are_capped_at_five() -> None:
    schema = {"type": "array", "items": {"type": "string"}}
    found: list[str] = []
    validate_instance(schema, list(range(10)), "$", found)
    assert len(found) == 5
    result = check({"type": "json_schema", "schema": schema}, "[1,2,3,4,5,6]")
    assert result.detail.count(";") == 4


def test_json_schema_assertion_end_to_end() -> None:
    ok = check({"type": "json_schema", "schema": {"type": "object"}}, '```\n{"a": 1}\n```')
    assert ok.passed
    assert ok.detail == "Output matches the JSON schema."
    invalid = check({"type": "json_schema", "schema": {"type": "object"}}, "{")
    assert not invalid.passed
    assert invalid.detail.startswith("Invalid JSON:")
    nested = "[" * 100_000 + "]" * 100_000
    deep = check({"type": "json_schema", "schema": {}}, nested)
    assert not deep.passed


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "decimal"},
        {"type": []},
        {"properties": []},
        {"properties": {"a": "string"}},
        {"required": "a"},
        {"additionalProperties": {}},
        {"minItems": -1},
        {"maxLength": True},
        {"enum": []},
        {"pattern": "("},
        {"pattern": 1},
        {"minimum": "1"},
        {"oneOf": []},
        {"const": float("nan")},
        "not an object",
        {"description": "x" * 20_000},
    ],
)
def test_schema_definition_errors(schema) -> None:
    with pytest.raises(SchemaDefinitionError):
        check_schema(schema)


def test_schema_depth_limits() -> None:
    deep: dict = {"type": "string"}
    for _ in range(10):
        deep = {"items": deep}
    with pytest.raises(SchemaDefinitionError, match="deeper than 10"):
        check_schema(deep)
    nested_value: list = []
    for _ in range(70):
        nested_value = [nested_value]
    with pytest.raises(SchemaDefinitionError, match="too deeply"):
        check_schema({"const": nested_value})
    check_schema({"const": {"a": [1, {"b": None}]}, "description": "fine"})


def test_json_equal() -> None:
    assert json_equal(1, 1.0)
    assert not json_equal(True, 1)
    assert json_equal(False, False)
    assert json_equal([1, {"a": "x"}], [1.0, {"a": "x"}])
    assert not json_equal([1], [1, 2])
    assert not json_equal({"a": 1}, {"b": 1})
    assert not json_equal("1", 1)


def test_strip_fences() -> None:
    assert strip_fences("```json\n{}\n```") == "{}"
    assert strip_fences("  ```\n{}") == "{}"
    assert strip_fences(" plain ") == "plain"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"score": 4, "reason": "good"}', (4, "good")),
        ('Sure! ```json\n{"score": 5}\n``` done', (5, "")),
        ('{"score": 3.0, "reason": 7}', (3, "")),
        ('{"score": "2"}', (2, "")),
        ('{"score": " 4.0 "}', (4, "")),
        ('{"score": "two"}', None),
        ('{"score": 2.5}', None),
        ('{"score": 6}', None),
        ('{"score": true}', None),
        ('{"reason": "no score"}', None),
        ("no json at all", None),
        ("{not json}", None),
        ("[1, 2]", None),
        ('["{", "}"]', None),
    ],
)
def test_parse_judge_reply(text: str, expected) -> None:
    assert parse_judge_reply(text) == expected


def test_case_status() -> None:
    from app.schemas import AssertionResult

    def result(passed: bool, error: str | None = None) -> AssertionResult:
        return AssertionResult(type="contains", passed=passed, score=None, detail="", error=error)

    assert case_status([result(True), result(True)]) == ("passed", 1.0)
    assert case_status([result(True), result(False)]) == ("failed", 0.5)
    assert case_status([result(True), result(False, "boom")]) == ("error", 0.5)
    assert case_status([]) == ("passed", 0.0)


def test_assertion_defaults_are_normalized() -> None:
    from app.services.evaluation import normalize_assertions

    normalized = normalize_assertions(
        [
            {"type": "contains", "value": "x"},
            {"type": "equals", "value": "x"},
            {"type": "regex", "pattern": "a", "flags": "si"},
            {"type": "llm_judge", "rubric": "r"},
            {"type": "json_schema", "schema": {"type": "object"}},
        ]
    )
    assert normalized == [
        {"type": "contains", "value": "x", "case_sensitive": False},
        {"type": "equals", "value": "x", "case_sensitive": True, "trim": True},
        {"type": "regex", "pattern": "a", "flags": "is"},
        {"type": "llm_judge", "rubric": "r", "threshold": 4, "judge_model": None},
        {"type": "json_schema", "schema": {"type": "object"}},
    ]
    with pytest.raises(ValueError, match="flags"):
        normalize_assertions([{"type": "regex", "pattern": "a", "flags": "ii"}])
