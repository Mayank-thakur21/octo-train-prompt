"""Deterministic offline provider used when no real provider key is configured.

Output depends only on the model id, system prompt and prompt (no randomness, no clock values),
so tests and demos are reproducible. Directives of the form ``[[demo:...]]`` in the prompt
exercise special paths (echo, JSON, refusals, delays and errors).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.providers.base import (
    REFUSAL_WARNING,
    Completed,
    FinishReason,
    GenerationRequest,
    GenerationResult,
    Provider,
    ProviderError,
    ProviderErrorKind,
    ProviderName,
    StreamEvent,
    TextDelta,
    ThinkingDelta,
    estimate_tokens,
)

DIRECTIVE_OPEN = "[[demo:"
DIRECTIVE_CLOSE = "]]"
_JUDGE_TERM = re.compile(r"[a-z0-9]{4,}")
_CHUNK = re.compile(r"\S+\s*|\s+")
_WORD_END = re.compile(r"\S+")
MAX_DELAY_MS = 10_000
SUMMARY_CHARS = 120
RETRY_AFTER_SECONDS = 7.0

JUDGE_STOP_WORDS = frozenset(
    {
        "that", "this", "with", "should", "must", "have", "response", "output", "answer",
        "from", "into", "about", "their", "there", "which", "would", "could",
    }
)  # fmt: skip

OBSERVATIONS: tuple[str, ...] = (
    "A clear statement of the goal usually improves the first answer more than extra detail.",
    "Concrete examples of the expected output help a model match the format you want.",
    "Splitting a large task into numbered steps makes the response easier to check.",
    "Stating the audience and tone up front keeps the wording consistent.",
    "Constraints such as length limits work best when they are explicit and measurable.",
    "Asking for a short justification can make a model's choices easier to review.",
    "Putting reference material before the question keeps the instruction easy to find.",
    "Naming what to avoid is often as useful as naming what to include.",
)

TIPS: tuple[str, ...] = (
    "Try the same prompt on two models in the Compare view to see how they differ.",
    "Save a prompt to the library to keep every version and diff the changes.",
    "Add template variables such as {{topic}} to reuse a prompt with new inputs.",
    "Build a test suite with assertions to check prompt changes automatically.",
    "Use an LLM judge assertion to grade answers against a rubric.",
)


@dataclass(frozen=True)
class _Plan:
    """What the demo model will do for one request."""

    text: str
    thinking: str | None
    finish: FinishReason
    delay_ms: int
    error: ProviderErrorKind | None
    seed: int
    seed_hex: str


def find_directives(prompt: str) -> tuple[list[str], str]:
    r"""Bodies of every ``[[demo:...]]`` directive, and the prompt with all of them removed.

    Finds exactly the matches of ``re.finditer(r"\[\[demo:([^\]]*)\]\]", prompt)``: a body
    runs to the first ``]``, which must be followed by another ``]``. That regex takes quadratic
    time because every unterminated ``[[demo:`` rescans to the end of the text; here the first
    ``]`` is looked up once and reused while it lies ahead, so the scan is linear.
    """
    bodies: list[str] = []
    kept: list[str] = []
    copied_to = search_from = 0
    bracket = -1  # first "]" at or after the current body start, once looked up
    while (start := prompt.find(DIRECTIVE_OPEN, search_from)) >= 0:
        body_start = start + len(DIRECTIVE_OPEN)
        if bracket < body_start:
            bracket = prompt.find("]", body_start)
            if bracket < 0:
                break  # no "]" left, so no later directive can close either
        if prompt.startswith(DIRECTIVE_CLOSE, bracket):
            bodies.append(prompt[body_start:bracket])
            kept.append(prompt[copied_to:start])
            copied_to = search_from = bracket + len(DIRECTIVE_CLOSE)
        else:
            search_from = start + 1
    kept.append(prompt[copied_to:])
    return bodies, "".join(kept)


def _parse_directives(prompt: str) -> tuple[str, set[str], int, ProviderErrorKind | None]:
    """Strip every directive; return (cleaned prompt, flags, delay ms, error kind)."""
    flags: set[str] = set()
    delay_ms = 0
    error: ProviderErrorKind | None = None
    bodies, cleaned = find_directives(prompt)
    for body in bodies:
        directive = body.strip()
        name, _, value = directive.partition("=")
        name = name.strip().lower()
        value = value.strip()
        if name in {"echo", "json", "refuse"} and not value:
            flags.add(name)
        elif name == "delay":
            try:
                delay_ms = max(0, min(MAX_DELAY_MS, int(value)))
            except ValueError:
                continue
        elif name == "error":
            try:
                error = ProviderErrorKind(value.lower())
            except ValueError:
                continue
    return cleaned, flags, delay_ms, error


def _section(text: str, start_tag: str, end_tag: str, *, last_end: bool) -> str | None:
    start = text.find(start_tag)
    if start < 0:
        return None
    end = text.rfind(end_tag) if last_end else text.find(end_tag, start)
    if end < start:
        return None
    return text[start + len(start_tag) : end]


def judge_text(prompt: str) -> str | None:
    """Heuristic judge verdict when the prompt looks like a judge request, else ``None``."""
    rubric = _section(prompt, "<rubric>", "</rubric>", last_end=False)
    output = _section(prompt, "<output>", "</output>", last_end=True)
    if rubric is None or output is None:
        return None
    terms: list[str] = []
    for term in _JUDGE_TERM.findall(rubric.lower()):
        if term not in JUDGE_STOP_WORDS and term not in terms:
            terms.append(term)
    lowered = output.lower()
    matched = sum(1 for term in terms if term in lowered)
    score = 3 if not terms else 1 + int(4 * matched / len(terms) + 0.5)
    reason = f"Demo judge: {matched}/{len(terms)} rubric terms found in the output."
    return json.dumps({"reason": reason, "score": score}, sort_keys=True)


def _summary(cleaned: str) -> str:
    collapsed = re.sub(r"\s+", " ", cleaned).strip()
    if len(collapsed) > SUMMARY_CHARS:
        return collapsed[:SUMMARY_CHARS] + "…"
    return collapsed


def _truncate(text: str, max_tokens: int) -> tuple[str, bool]:
    """Longest whole-word prefix whose estimate fits ``max_tokens``."""
    if estimate_tokens(text) <= max_tokens:
        return text, False
    limit = max_tokens * 4
    best = 0
    for match in _WORD_END.finditer(text):
        if match.end() > limit:
            break
        best = match.end()
    return text[:best], True


class DemoProvider(Provider):
    """Offline provider with deterministic, prompt-derived output."""

    name = ProviderName.DEMO

    def __init__(self, *, stream_delay_ms: int = 20) -> None:
        self._stream_delay_s = stream_delay_ms / 1000

    def is_configured(self) -> bool:
        return True

    def _plan(self, req: GenerationRequest) -> _Plan:
        spec = req.model
        system = req.system or ""
        seed_hex = hashlib.sha256(f"{spec.id}\x1f{system}\x1f{req.prompt}".encode()).hexdigest()
        seed = int(seed_hex[:8], 16)
        cleaned, flags, delay_ms, error = _parse_directives(req.prompt)
        word_count = len(cleaned.split())
        concise = spec.id != "demo-verbose"
        finish: FinishReason = "stop"

        judged = None if flags & {"echo", "json"} else judge_text(cleaned)
        if "refuse" in flags:
            text, finish = "", "refusal"
        elif "echo" in flags:
            text = cleaned.strip()
        elif "json" in flags:
            text = json.dumps(
                {"echo": cleaned[:80], "model": spec.id, "words": word_count}, sort_keys=True
            )
        elif judged is not None:
            text = judged
        elif concise:
            text = (
                f"This is an offline demo response from {spec.display_name}.\n\n"
                f'You asked: "{_summary(cleaned)}"\n\n'
                f"{OBSERVATIONS[seed % len(OBSERVATIONS)]}"
            )
        else:
            n = len(OBSERVATIONS)
            lines = [
                "## Demo response",
                "",
                f"This answer was produced offline by {spec.display_name}. Configure an "
                "Anthropic, OpenAI or Google Gemini API key to get real model output.",
                "",
                f'**Your prompt** ({word_count} words): "{_summary(cleaned)}"',
                "",
                f"- {OBSERVATIONS[seed % n]}",
                f"- {OBSERVATIONS[(seed // n) % n]}",
                f"- {TIPS[seed % len(TIPS)]}",
            ]
            if system:
                lines += ["", f"_System prompt applied ({len(system)} characters)._"]
            text = "\n".join(lines)

        if finish != "refusal":
            text, truncated = _truncate(text, req.max_tokens)
            if truncated:
                finish = "length"
        thinking = None
        if req.thinking:
            style = "concise" if concise else "detailed"
            thinking = f"Reading the prompt ({word_count} words) and drafting a {style} answer."
        return _Plan(text, thinking, finish, delay_ms, error, seed, seed_hex)

    def _result(self, req: GenerationRequest, plan: _Plan, *, streamed: bool) -> GenerationResult:
        return GenerationResult(
            text=plan.text,
            thinking=plan.thinking,
            input_tokens=estimate_tokens(req.system) + estimate_tokens(req.prompt),
            output_tokens=estimate_tokens(plan.text),
            latency_ms=80 + plan.seed % 420 + plan.delay_ms,
            ttft_ms=(20 + plan.seed % 60 + plan.delay_ms) if streamed else None,
            finish_reason=plan.finish,
            request_id="demo_" + plan.seed_hex[:24],
            warnings=[REFUSAL_WARNING] if plan.finish == "refusal" else [],
        )

    def _error(self, kind: ProviderErrorKind) -> ProviderError:
        retry = (
            RETRY_AFTER_SECONDS
            if kind in {ProviderErrorKind.RATE_LIMITED, ProviderErrorKind.OVERLOADED}
            else None
        )
        return ProviderError(kind, self.name, retry_after=retry)

    async def generate(self, req: GenerationRequest) -> GenerationResult:
        plan = self._plan(req)
        if plan.error is not None:
            raise self._error(plan.error)
        if plan.delay_ms:
            await asyncio.sleep(plan.delay_ms / 1000)
        return self._result(req, plan, streamed=False)

    async def stream(self, req: GenerationRequest) -> AsyncIterator[StreamEvent]:
        plan = self._plan(req)
        if plan.delay_ms:
            await asyncio.sleep(plan.delay_ms / 1000)
        if plan.thinking:
            yield ThinkingDelta(plan.thinking)
        pieces = _CHUNK.findall(plan.text)
        chunks = ["".join(pieces[i : i + 3]) for i in range(0, len(pieces), 3)]
        for index, chunk in enumerate(chunks):
            if index and self._stream_delay_s:
                await asyncio.sleep(self._stream_delay_s)
            yield TextDelta(chunk)
            if plan.error is not None:
                raise self._error(plan.error)
        if plan.error is not None:  # empty text: fail before any output
            raise self._error(plan.error)
        yield Completed(self._result(req, plan, streamed=True))
