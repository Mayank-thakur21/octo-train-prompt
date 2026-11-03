"""Version diff: minimal edit scripts, difflib-compatible unified text and bounded running time."""

from __future__ import annotations

import difflib
import random
import time
from itertools import pairwise

import pytest

from app.services.diff import Opcode, diff_text, line_opcodes, unified_text


def _apply(a: list[str], b: list[str], codes: list[Opcode]) -> list[str]:
    """Replay opcodes on ``a``; checks they are contiguous and that equal ranges really match."""
    out: list[str] = []
    i = j = 0
    for tag, i1, i2, j1, j2 in codes:
        assert (i1, j1) == (i, j)
        if tag == "equal":
            assert a[i1:i2] == b[j1:j2]
        out += b[j1:j2]
        i, j = i2, j2
    assert (i, j) == (len(a), len(b))
    return out


def _lcs(a: list[str], b: list[str]) -> int:
    row = [0] * (len(b) + 1)
    for x in reversed(a):
        prev = row[:]
        for j in range(len(b) - 1, -1, -1):
            row[j] = prev[j + 1] + 1 if x == b[j] else max(prev[j], row[j + 1])
    return row[0]


def test_opcodes_are_valid_and_minimal_on_random_inputs() -> None:
    rng = random.Random(1103)  # noqa: S311 - reproducible test data, not a secret
    for _ in range(3000):
        a = [rng.choice("abcx") for _ in range(rng.randint(0, 12))]
        b = [rng.choice("abcy") for _ in range(rng.randint(0, 12))]
        codes = line_opcodes(a, b)
        assert _apply(a, b, codes) == b
        equal = sum(i2 - i1 for tag, i1, i2, _, _ in codes if tag == "equal")
        assert equal == _lcs(a, b), (a, b, codes)
        # Adjacent opcodes are never both equal or both changes.
        assert all((x[0] == "equal") != (y[0] == "equal") for x, y in pairwise(codes))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("a\nb\nc", "a\nB\nc\nd"),
        ("\n".join(str(i) for i in range(30)), "\n".join(str(i) for i in range(30) if i != 15)),
        ("x\n" * 3 + "\n".join(map(str, range(20))), "\n".join(map(str, range(20))) + "\ny"),
        ("", "one\ntwo"),
        ("one\ntwo", ""),
    ],
)
def test_unified_text_matches_difflib(old: str, new: str) -> None:
    a, b = old.splitlines(), new.splitlines()
    codes = line_opcodes(a, b)
    assert codes == difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    expected = "\n".join(difflib.unified_diff(a, b, "v1", "v2", n=3, lineterm=""))
    assert unified_text(a, b, codes, "v1", "v2") == expected


def test_over_budget_falls_back_to_one_replace_around_common_lines() -> None:
    a = ["head", "a1", "a2", "a3", "tail"]
    b = ["head", "b1", "b2", "tail"]
    assert line_opcodes(a, b, budget=1) == [
        ("equal", 0, 1, 0, 1),
        ("replace", 1, 4, 1, 3),
        ("equal", 4, 5, 3, 4),
    ]


@pytest.mark.parametrize(
    ("old", "new"),
    [
        # Repeated lines made difflib (autojunk off) quadratic: 20,000 lines took 97 s.
        ("\n" * 50_000, "\n" * 50_000 + "x"),
        ("\n" * 50_000 + "p", "q\n" + "\n" * 50_000),
        ("a\nx\n" * 25_000, "a\ny\n" * 25_000),
        ("\n".join(f"a{i}" for i in range(50_000)), "\n".join(f"b{i}" for i in range(50_000))),
    ],
)
def test_diff_time_is_bounded(old: str, new: str) -> None:
    started = time.perf_counter()
    diff = diff_text(old, new, 1, 2)
    elapsed = time.perf_counter() - started
    # Each case took minutes with difflib. The bounded diff needs well under a second; the bound
    # is loose because CI runs these tests under coverage tracing, which slows the loop down.
    assert elapsed < 10.0, f"{elapsed:.2f}s"
    # Still a correct diff: the kept and inserted lines rebuild the new text, and the kept and
    # deleted lines rebuild the old one.
    assert [line.text for line in diff.lines if line.op != "delete"] == new.splitlines()
    assert [line.text for line in diff.lines if line.op != "insert"] == old.splitlines()


def test_appended_line_after_many_blank_lines_is_one_insert() -> None:
    started = time.perf_counter()
    diff = diff_text("\n" * 50_000, "\n" * 50_000 + "x", 1, 2)
    assert time.perf_counter() - started < 5.0  # 97 s for 20,000 lines before
    assert (diff.added, diff.removed) == (1, 0)
    assert diff.lines[-1].text == "x"
    assert diff.unified.endswith("+x")
