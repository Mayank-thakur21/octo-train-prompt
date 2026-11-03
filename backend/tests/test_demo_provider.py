"""Demo provider: determinism, directives, judge heuristic, truncation and streaming."""

from __future__ import annotations

import json
import random
import re
import time

import pytest

from app.providers.base import (
    REFUSAL_WARNING,
    Completed,
    GenerationRequest,
    ProviderError,
    ProviderErrorKind,
    TextDelta,
    ThinkingDelta,
)
from app.providers.catalog import DEMO_MODELS
from app.providers.demo import OBSERVATIONS, TIPS, DemoProvider, find_directives, judge_text

CONCISE, VERBOSE = DEMO_MODELS


def req(
    prompt: str,
    *,
    model=CONCISE,
    system: str | None = None,
    thinking: bool = False,
    max_tokens: int = 4096,
) -> GenerationRequest:
    return GenerationRequest(
        model=model,
        system=system,
        prompt=prompt,
        temperature=0.7,
        max_tokens=max_tokens,
        thinking=thinking,
        timeout_s=10,
    )


async def stream_events(provider: DemoProvider, request: GenerationRequest) -> list[object]:
    return [event async for event in provider.stream(request)]


def test_constants_are_large_enough() -> None:
    assert len(OBSERVATIONS) >= 6
    assert len(TIPS) >= 4


async def test_concise_output_is_deterministic() -> None:
    provider = DemoProvider(stream_delay_ms=0)
    first = await provider.generate(req("Explain   prompt\ncaching"))
    second = await provider.generate(req("Explain   prompt\ncaching"))
    assert first == second
    assert first.text.startswith(
        "This is an offline demo response from Demo Concise (offline).\n\n"
        'You asked: "Explain prompt caching"'
    )
    assert first.finish_reason == "stop"
    assert first.request_id is not None
    assert first.request_id.startswith("demo_")
    assert len(first.request_id) == len("demo_") + 24
    assert first.input_tokens == 6
    assert first.ttft_ms is None
    assert 80 <= first.latency_ms < 500
    other = await provider.generate(req("Something else entirely"))
    assert other.request_id != first.request_id


async def test_verbose_output_mentions_system_prompt() -> None:
    provider = DemoProvider(stream_delay_ms=0)
    result = await provider.generate(req("one two three", model=VERBOSE, system="Be kind."))
    assert result.text.startswith("## Demo response")
    assert "**Your prompt** (3 words)" in result.text
    assert result.text.count("\n- ") == 3
    assert result.text.endswith("_System prompt applied (8 characters)._")
    without = await provider.generate(req("one two three", model=VERBOSE))
    assert "System prompt applied" not in without.text


async def test_long_prompt_summary_is_truncated() -> None:
    result = await DemoProvider().generate(req("word " * 100))
    assert "…" in result.text


async def test_echo_json_and_refuse_directives() -> None:
    provider = DemoProvider(stream_delay_ms=0)
    echo = await provider.generate(req("  [[demo:echo]] repeat me  "))
    assert echo.text == "repeat me"
    as_json = await provider.generate(req("[[demo:json]]count these words"))
    assert json.loads(as_json.text) == {
        "echo": "count these words",
        "model": "demo-concise",
        "words": 3,
    }
    refused = await provider.generate(req("[[demo:refuse]] nope"))
    assert refused.text == ""
    assert refused.finish_reason == "refusal"
    assert refused.warnings == [REFUSAL_WARNING]
    unknown = await provider.generate(req("[[demo:wat]] [[demo:delay=abc]] [[demo:error=nope]] hi"))
    assert '"hi"' in unknown.text


@pytest.mark.parametrize("kind", list(ProviderErrorKind))
async def test_error_directive_generate_raises_immediately(kind: ProviderErrorKind) -> None:
    with pytest.raises(ProviderError) as info:
        await DemoProvider().generate(req(f"[[demo:error={kind.value}]] hi"))
    assert info.value.kind is kind
    expected = (
        7.0 if kind in {ProviderErrorKind.RATE_LIMITED, ProviderErrorKind.OVERLOADED} else None
    )
    assert info.value.retry_after == expected


async def test_error_directive_stream_yields_first_chunk_then_raises() -> None:
    provider = DemoProvider(stream_delay_ms=0)
    seen: list[object] = []

    async def consume() -> None:
        async for event in provider.stream(req("[[demo:error=overloaded]] hello there friend")):
            seen.append(event)

    with pytest.raises(ProviderError):
        await consume()
    assert len(seen) == 1
    assert isinstance(seen[0], TextDelta)


async def test_error_with_empty_text_raises_in_stream() -> None:
    with pytest.raises(ProviderError):
        await stream_events(DemoProvider(), req("[[demo:refuse]][[demo:error=auth]]"))


async def test_stream_chunks_concatenate_to_text_with_thinking() -> None:
    provider = DemoProvider(stream_delay_ms=1)
    request = req("stream this prompt please", thinking=True, model=VERBOSE)
    events = await stream_events(provider, request)
    assert isinstance(events[0], ThinkingDelta)
    assert events[0].text == "Reading the prompt (4 words) and drafting a detailed answer."
    final = events[-1]
    assert isinstance(final, Completed)
    text = "".join(event.text for event in events if isinstance(event, TextDelta))
    assert text == final.result.text
    assert final.result.thinking == events[0].text
    assert final.result.ttft_ms is not None
    assert len([e for e in events if isinstance(e, TextDelta)]) > 1


async def test_delay_directive_is_clamped_and_added_to_latency() -> None:
    result = await DemoProvider().generate(req("[[demo:delay=1]] hi"))
    base = await DemoProvider().generate(req("[[demo:delay=0]] hi"))
    assert result.latency_ms != base.latency_ms or result.text == base.text
    from app.providers.demo import _parse_directives

    assert _parse_directives("[[demo:delay=999999]]")[2] == 10_000
    assert _parse_directives("[[demo:delay=-5]]")[2] == 0


async def test_max_tokens_truncates_on_word_boundary() -> None:
    result = await DemoProvider().generate(
        req("[[demo:echo]] alpha beta gamma delta", max_tokens=3)
    )
    assert result.finish_reason == "length"
    assert result.text == "alpha beta"
    tiny = await DemoProvider().generate(req("[[demo:echo]] supercalifragilistic", max_tokens=1))
    assert tiny.text == ""
    assert tiny.finish_reason == "length"


def test_judge_heuristic() -> None:
    prompt = (
        "<rubric>\nMentions Paris and France, with the population.\n</rubric>\n\n"
        "<input>\nq\n</input>\n\n<output>\nParis is in France.\n</output>"
    )
    verdict = json.loads(judge_text(prompt) or "")
    # terms: mentions, paris, france, population -> 2 of 4 matched
    assert verdict == {"reason": "Demo judge: 2/4 rubric terms found in the output.", "score": 3}
    empty = json.loads(judge_text("<rubric>be ok</rubric><output>x</output>") or "")
    assert empty["score"] == 3
    assert judge_text("no tags here") is None
    assert judge_text("<rubric>x</rubric> <output> no end") is None


async def test_judge_mode_through_generate() -> None:
    prompt = "<rubric>\nsunny weather\n</rubric>\n<output>\nIt is sunny weather today.\n</output>"
    result = await DemoProvider().generate(req(prompt))
    assert json.loads(result.text)["score"] == 5
    echoed = await DemoProvider().generate(req("[[demo:echo]]" + prompt))
    assert echoed.text.startswith("<rubric>")


# The section 5.7 directive regex, used only as a reference on short inputs (it is quadratic).
REFERENCE_DIRECTIVE = re.compile(r"\[\[demo:([^\]]*)\]\]")


def test_find_directives_matches_the_reference_regex() -> None:
    pieces = ["[[demo:", "[", "]", "]]", "echo", "x", " ", "\n", "[[demo:json]]"]
    rng = random.Random(57)  # noqa: S311 - reproducible test data, not a secret
    for _ in range(20_000):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 10)))
        expected = (REFERENCE_DIRECTIVE.findall(text), REFERENCE_DIRECTIVE.sub("", text))
        assert find_directives(text) == expected, repr(text)


@pytest.mark.parametrize(
    "hostile",
    ["[[demo:" * 30_000, "[[demo:]" * 25_000, "[[demo:x" * 25_000 + "]]"],
)
async def test_directive_parsing_takes_linear_time(hostile: str) -> None:
    # The regex took about 21 s on 100,000 characters of "[[demo:"; this is 200,000.
    started = time.perf_counter()
    result = await DemoProvider().generate(req(hostile + " hi"))
    assert time.perf_counter() - started < 3.0  # loose for CI under coverage; milliseconds here
    assert result.finish_reason == "stop"
