"""Template grammar: the shared vectors, legacy conversion and built-in templates."""

from __future__ import annotations

import random
import re
import time

import pytest

from app.services import templating

A65 = "a" * 65

# The section 4.1 regex. ``templating.scan`` must find exactly its matches; it is only used here,
# on short inputs, because it takes quadratic time on unterminated defaults.
REFERENCE_PATTERN = re.compile(
    r"(?P<escape>\\\{\{)"
    r"|\{\{\s*(?P<name>[A-Za-z_][A-Za-z0-9_]{0,63})\s*(?:\|(?P<default>[^\n]*?))?\}\}"
)
FUZZ_PIECES = (
    "{", "}", "{{", "}}", "|", "\\", "\n", " ", "a", "b", "_", "1", "\t",
    "{{a|", "{{ a ", "\\{{",
)  # fmt: skip

# (system, prompt, variables, rendered prompt (strict) or None for 422, extracted)
VECTORS = [
    (None, "Hello {{name}}!", {"name": "Ada"}, "Hello Ada!", [("name", None, True)]),
    (None, "Hi {{ name }}", {"name": "Ada"}, "Hi Ada", [("name", None, True)]),
    (None, "{{tone|friendly}} tone", {}, "friendly tone", [("tone", "friendly", False)]),
    (
        None,
        "{{tone|friendly}} and {{tone}}",
        {},
        "friendly and friendly",
        [("tone", "friendly", False)],
    ),
    (None, "{{tone}} and {{tone|calm}}", {}, "calm and calm", [("tone", "calm", False)]),
    (None, "{{a|x|y}}", {}, "x|y", [("a", "x|y", False)]),
    (None, "[{{a|}}]", {}, "[]", [("a", "", False)]),
    (
        None,
        "{{ name | Ada Lovelace }}",
        {},
        "Ada Lovelace",
        [("name", "Ada Lovelace", False)],
    ),
    (None, "\\{{name}}", {}, "{{name}}", []),
    (None, "{{not valid}} {{1abc}}", {}, "{{not valid}} {{1abc}}", []),
    (None, '{"json": {"a": 1}}', {}, '{"json": {"a": 1}}', []),
    (None, "{{{name}}}", {"name": "Ada"}, "{Ada}", [("name", None, True)]),
    (None, "{{a}}", {"a": "{{b}}"}, "{{b}}", [("a", None, True)]),
    (None, "[{{a|x}}]", {"a": ""}, "[]", [("a", "x", False)]),
    (None, "{{a|line1\nline2}}", {}, "{{a|line1\nline2}}", []),
    (None, "{{" + A65 + "}}", {}, "{{" + A65 + "}}", []),
    ("{{b}}", "{{a}} {{b}}", {"a": "1", "b": "2"}, "1 2", [("b", None, True), ("a", None, True)]),
    (
        None,
        "{{a}} {{b}} {{c|z}}",
        {"a": "1"},
        None,
        [("a", None, True), ("b", None, True), ("c", "z", False)],
    ),
]


@pytest.mark.parametrize(("system", "prompt", "variables", "expected", "extracted"), VECTORS)
def test_shared_vectors(system, prompt, variables, expected, extracted) -> None:
    infos = templating.extract_variables(system, prompt)
    assert [(info.name, info.default, info.required) for info in infos] == extracted
    rendered = templating.render(system, prompt, variables)
    if expected is None:
        assert rendered.missing == ["b"]
    else:
        assert rendered.missing == []
        assert rendered.prompt == expected


def test_vector_17_renders_system_too() -> None:
    rendered = templating.render("{{b}}", "{{a}} {{b}}", {"a": "1", "b": "2"})
    assert rendered.system == "2"


def test_vector_18_lenient_render_keeps_missing_placeholder() -> None:
    rendered = templating.render(None, "{{a}} {{b}} {{c|z}}", {"a": "1"})
    assert rendered.prompt == "1 {{b}} z"
    assert rendered.missing == ["b"]


def test_missing_names_are_sorted_and_unique() -> None:
    rendered = templating.render("{{zeta}}", "{{beta}} {{alpha}} {{beta}}", {})
    assert rendered.missing == ["alpha", "beta", "zeta"]


def test_variable_names_and_as_dict() -> None:
    assert templating.variable_names("{{s}}", "{{p|d}} {{s}}") == ["s", "p"]
    info = templating.extract_variables(None, "{{x|1}}")[0]
    assert info.as_dict() == {"name": "x", "default": "1", "required": False}


def test_normalize_system() -> None:
    assert templating.normalize_system(None) is None
    assert templating.normalize_system("  \n ") is None
    assert templating.normalize_system(" keep ") == " keep "


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Summarize {text}", "Summarize {{text}}"),
        ("{{text}}", "{{text}}"),
        ('{"a": 1}', '{"a": 1}'),
        ("{a} and {b}", "{{a}} and {{b}}"),
        ("\\{a}", "\\{a}"),
    ],
)
def test_legacy_conversion(text: str, expected: str) -> None:
    assert templating.convert_legacy_placeholders(text) == expected


def test_builtin_templates_render_with_defaults() -> None:
    ids = [template.id for template in templating.BUILTIN_TEMPLATES]
    assert ids == [
        "summarizer",
        "code-reviewer",
        "email-writer",
        "idea-generator",
        "explainer",
        "translator",
        "bug-fixer",
        "blog-writer",
        "structured-extractor",
        "sentiment-classifier",
    ]
    for template in templating.BUILTIN_TEMPLATES:
        data = template.as_dict()
        required = {item["name"] for item in data["variables"] if item["required"]}
        values = dict.fromkeys(required, "value")
        rendered = templating.render(template.system, template.prompt, values)
        assert rendered.missing == []
        assert "{{" not in rendered.prompt
        assert data["description"].endswith(".")


def test_builtin_template_defaults() -> None:
    by_id = {template.id: template.as_dict() for template in templating.BUILTIN_TEMPLATES}
    email = {item["name"]: item["default"] for item in by_id["email-writer"]["variables"]}
    assert email == {"topic": None, "tone": "professional", "length": "short"}
    ideas = {item["name"]: item["default"] for item in by_id["idea-generator"]["variables"]}
    assert ideas == {"count": "10", "topic": None}
    assert by_id["summarizer"]["prompt"] == (
        "Summarize the following text in 3 bullet points:\n\n{{text}}"
    )
    assert by_id["sentiment-classifier"]["tags"] == ["data", "classification"]


def _reference_tokens(text: str) -> list[tuple[int, int, str | None, str | None]]:
    return [
        (match.start(), match.end(), match.group("name"), match.group("default"))
        for match in REFERENCE_PATTERN.finditer(text)
    ]


def _scan_tokens(text: str) -> list[tuple[int, int, str | None, str | None]]:
    return [(token.start, token.end, token.name, token.default) for token in templating.scan(text)]


def test_scan_matches_the_reference_regex_on_random_inputs() -> None:
    rng = random.Random(20261103)  # noqa: S311 - reproducible test data, not a secret
    for _ in range(20_000):
        text = "".join(rng.choice(FUZZ_PIECES) for _ in range(rng.randint(0, 14)))
        assert _scan_tokens(text) == _reference_tokens(text), repr(text)


@pytest.mark.parametrize("size", [63, 64, 65])
def test_scan_matches_the_reference_at_the_name_length_limit(size: int) -> None:
    text = "{{" + "a" * size + "}} {{" + "b" * size + "|d}} {{c|{{d}}"
    assert _scan_tokens(text) == _reference_tokens(text)


@pytest.mark.parametrize(
    "hostile",
    [
        "{{a|" * 25_000,
        # A "}}" at the very end keeps the scanner's main loop busy on every line.
        ("{{a|" * 2_500 + "\n") * 10 + "}}",
        "{{a|x}" * 20_000,
        "\\{{a|" * 20_000,
        "{{" + " " * 100_000,
        "{{ a " * 25_000,
    ],
)
def test_render_and_extract_take_linear_time(hostile: str) -> None:
    started = time.perf_counter()
    assert templating.extract_variables(hostile, hostile) == []
    rendered = templating.render(hostile, hostile, {"a": "x"})
    elapsed = time.perf_counter() - started
    assert rendered.missing == []
    # The regex needed about 110 s for one 100,000-character text. The scanner needs well under
    # 0.1 s for both (the bound is loose for slow CI machines running with coverage tracing).
    assert elapsed < 5.0, f"{elapsed:.2f}s"
