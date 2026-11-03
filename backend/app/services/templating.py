r"""Template grammar: ``{{name}}``, ``{{name|default}}`` and the ``\{{`` escape.

The grammar is defined by this regex (contract section 4.1)::

    (?P<escape>\\\{\{)|\{\{\s*(?P<name>[A-Za-z_][A-Za-z0-9_]{0,63})\s*(?:\|(?P<default>[^\n]*?))?\}\}

Running that regex directly takes quadratic time: at every ``{{name|`` without a closing ``}}``
on its line, the lazy default rescans to the end of the line. :func:`scan` finds exactly the
same matches in linear time. A short anchored regex matches the bounded head (``{{``, the name,
then ``|`` or ``}}``), and the end of a default comes from cached ``str.find`` lookups whose
positions only move forward. Substituted values are inserted verbatim and never re-scanned.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

# Everything a placeholder can contain before its default: ``{{``, optional whitespace, the
# name, optional whitespace, then ``}}`` (no default) or ``|`` (a default follows).
_HEAD_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]{0,63})\s*(\}\}|\|)")
LEGACY_PATTERN = re.compile(r"(?<![{\\])\{([A-Za-z_][A-Za-z0-9_]{0,63})\}(?!\})")
VARIABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


@dataclass(frozen=True)
class Token:
    """One grammar match: an escape (``name is None``) or a placeholder.

    ``text[start:end]`` is the whole match. ``default`` is the raw (untrimmed) default, or
    ``None`` when the placeholder declares none.
    """

    start: int
    end: int
    name: str | None
    default: str | None


class _ForwardFinder:
    """``text.find(needle, pos)`` with a cache, linear in total for non-decreasing ``pos``."""

    def __init__(self, text: str, needle: str) -> None:
        self._text = text
        self._needle = needle
        self._searched_from = -1
        self._found = -1

    def find(self, pos: int) -> int:
        # The cached answer still holds for a later ``pos`` unless ``pos`` moved past the hit:
        # nothing matched between the old start and the hit (or after it, for a miss).
        cached = pos >= self._searched_from >= 0 and (self._found == -1 or self._found >= pos)
        if not cached:
            self._searched_from = pos
            self._found = self._text.find(self._needle, pos)
        return self._found


def scan(text: str) -> Iterator[Token]:
    """Yield the grammar's matches left to right, as the section 4.1 regex would find them."""
    closes = _ForwardFinder(text, "}}")
    newlines = _ForwardFinder(text, "\n")
    pos = 0
    while True:
        brace = text.find("{{", pos)
        if brace < 0:
            return
        # ``\{{`` is the leftmost possible match when its backslash is still unscanned.
        if brace - 1 >= pos and text[brace - 1] == "\\":
            yield Token(brace - 1, brace + 2, None, None)
            pos = brace + 2
            continue
        if closes.find(brace + 2) < 0:
            # Every placeholder ends with "}}", so only escapes can follow.
            yield from _escapes(text, pos)
            return
        head = _HEAD_PATTERN.match(text, brace)
        if head is None:
            pos = brace + 1
            continue
        name = head.group(1)
        if head.group(2) == "}}":
            yield Token(brace, head.end(), name, None)
            pos = head.end()
            continue
        # A default runs from after ``|`` to the first ``}}`` and must not contain a newline.
        default_start = head.end()
        close = closes.find(default_start)
        newline = newlines.find(default_start)
        if close < 0 or 0 <= newline < close:
            pos = brace + 1
            continue
        yield Token(brace, close + 2, name, text[default_start:close])
        pos = close + 2


def _escapes(text: str, pos: int) -> Iterator[Token]:
    """The ``\\{{`` escapes at or after ``pos``."""
    while (start := text.find("\\{{", pos)) >= 0:
        yield Token(start, start + 3, None, None)
        pos = start + 3


@dataclass(frozen=True)
class VariableInfo:
    name: str
    default: str | None
    required: bool

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "default": self.default, "required": self.required}


@dataclass
class Rendered:
    """Result of rendering a system/prompt pair."""

    system: str | None
    prompt: str
    variables: list[VariableInfo]
    missing: list[str] = field(default_factory=list)


def _scan_all(text: str | None) -> list[Token]:
    return list(scan(text)) if text else []


def _variables(*token_lists: list[Token]) -> list[VariableInfo]:
    """Unique variables of the token lists in order; see :func:`extract_variables`."""
    defaults: dict[str, str | None] = {}
    for tokens in token_lists:
        for token in tokens:
            name = token.name
            if name is None:
                continue
            default = token.default.strip() if token.default is not None else None
            if name not in defaults or (defaults[name] is None and default is not None):
                defaults[name] = default
    return [
        VariableInfo(name=name, default=default, required=default is None)
        for name, default in defaults.items()
    ]


def extract_variables(system: str | None, prompt: str | None) -> list[VariableInfo]:
    """Unique variables in order of first appearance (system first, then prompt).

    ``default`` is the first default declared for the name anywhere; ``required`` is true when
    no default is declared anywhere.
    """
    return _variables(_scan_all(system), _scan_all(prompt))


def variable_names(system: str | None, prompt: str | None) -> list[str]:
    return [info.name for info in extract_variables(system, prompt)]


def render_text(
    text: str,
    tokens: list[Token],
    variables: dict[str, str],
    first_defaults: dict[str, str | None],
    missing: set[str],
) -> str:
    """Render one text from its ``tokens`` (from :func:`scan`).

    Missing placeholders are left verbatim and added to ``missing``.
    """
    parts: list[str] = []
    pos = 0
    for token in tokens:
        parts.append(text[pos : token.start])
        pos = token.end
        name = token.name
        if name is None:
            parts.append("{{")
        elif name in variables:
            parts.append(variables[name])
        elif token.default is not None:
            parts.append(token.default.strip())
        elif (fallback := first_defaults.get(name)) is not None:
            parts.append(fallback)
        else:
            missing.add(name)
            parts.append(text[token.start : token.end])
    parts.append(text[pos:])
    return "".join(parts)


def render(system: str | None, prompt: str, variables: dict[str, str] | None = None) -> Rendered:
    """Render system and prompt with the same variables (lenient: ``missing`` is reported).

    Callers in strict mode treat a non-empty ``missing`` list as an error. Each text is scanned
    once; its tokens serve both variable extraction and rendering.
    """
    values = variables or {}
    system_tokens = _scan_all(system)
    prompt_tokens = _scan_all(prompt)
    infos = _variables(system_tokens, prompt_tokens)
    first_defaults = {info.name: info.default for info in infos}
    missing: set[str] = set()
    rendered_system = (
        render_text(system, system_tokens, values, first_defaults, missing)
        if system is not None
        else None
    )
    rendered_prompt = render_text(prompt, prompt_tokens, values, first_defaults, missing)
    return Rendered(
        system=rendered_system, prompt=rendered_prompt, variables=infos, missing=sorted(missing)
    )


def normalize_system(system: str | None) -> str | None:
    """Empty or whitespace-only system prompts mean "no system prompt"."""
    if system is None or not system.strip():
        return None
    return system


def convert_legacy_placeholders(text: str) -> str:
    """Rewrite v1 single-brace placeholders (``{name}``) to ``{{name}}``."""
    return LEGACY_PATTERN.sub(r"{{\1}}", text)


@dataclass(frozen=True)
class BuiltinTemplate:
    id: str
    name: str
    description: str
    tags: tuple[str, ...]
    system: str | None
    prompt: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tags": list(self.tags),
            "system": self.system,
            "prompt": self.prompt,
            "variables": [info.as_dict() for info in extract_variables(self.system, self.prompt)],
        }


BUILTIN_TEMPLATES: tuple[BuiltinTemplate, ...] = (
    BuiltinTemplate(
        id="summarizer",
        name="Summarizer",
        description="Condenses a text into three bullet points.",
        tags=("writing",),
        system="You are a concise summarizer.",
        prompt="Summarize the following text in 3 bullet points:\n\n{{text}}",
    ),
    BuiltinTemplate(
        id="code-reviewer",
        name="Code Reviewer",
        description="Reviews a code snippet and suggests improvements.",
        tags=("code",),
        system="You are an expert software engineer focused on clean, efficient code.",
        prompt="Review this code and suggest improvements:\n\n```\n{{code}}\n```",
    ),
    BuiltinTemplate(
        id="email-writer",
        name="Email Writer",
        description="Drafts an email about a topic with a chosen tone and length.",
        tags=("writing", "business"),
        system="You are a professional business writer.",
        prompt=(
            "Write a professional email about: {{topic}}\n"
            "Tone: {{tone|professional}}\n"
            "Length: {{length|short}}"
        ),
    ),
    BuiltinTemplate(
        id="idea-generator",
        name="Idea Generator",
        description="Brainstorms a list of creative ideas for a topic.",
        tags=("creative",),
        system="You are a creative brainstorming expert.",
        prompt="Generate {{count|10}} creative ideas for: {{topic}}",
    ),
    BuiltinTemplate(
        id="explainer",
        name="Explainer",
        description="Explains a concept in simple terms for a given audience.",
        tags=("education",),
        system="You are a clear, patient teacher.",
        prompt="Explain {{concept}} to a {{audience|beginner}} in simple terms.",
    ),
    BuiltinTemplate(
        id="translator",
        name="Translator",
        description="Translates a text into another language.",
        tags=("language",),
        system="You are a professional translator.",
        prompt="Translate the following to {{language}}:\n\n{{text}}",
    ),
    BuiltinTemplate(
        id="bug-fixer",
        name="Bug Fixer",
        description="Fixes a bug in a code snippet and explains the cause.",
        tags=("code",),
        system="You are a debugging expert.",
        prompt=(
            "Fix the bug in this code and explain what was wrong:\n\n```\n{{code}}\n```\n"
            "Error: {{error}}"
        ),
    ),
    BuiltinTemplate(
        id="blog-writer",
        name="Blog Writer",
        description="Writes a structured blog post about a topic.",
        tags=("writing", "marketing"),
        system="You are a skilled blog writer.",
        prompt="Write a blog post about {{topic}}. Include: intro, 3 sections, conclusion.",
    ),
    BuiltinTemplate(
        id="structured-extractor",
        name="Structured Extractor",
        description="Extracts named fields from a text as a JSON object.",
        tags=("data",),
        system="You extract structured data and reply with valid JSON only.",
        prompt=(
            "Extract the following fields as a JSON object: {{fields|name, date, amount}}\n\n"
            "Text:\n{{text}}"
        ),
    ),
    BuiltinTemplate(
        id="sentiment-classifier",
        name="Sentiment Classifier",
        description="Labels the sentiment of a text as positive, negative or neutral.",
        tags=("data", "classification"),
        system="You are a precise sentiment classifier.",
        prompt=(
            "Classify the sentiment of the text as positive, negative or neutral. "
            "Reply with one word.\n\nText:\n{{text}}"
        ),
    ),
)
