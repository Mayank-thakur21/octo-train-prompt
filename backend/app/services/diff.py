"""Server-side line diff between two prompt versions.

``difflib.SequenceMatcher`` takes quadratic (or worse) time on repetitive input, and a prompt
version can hold 100,000 lines, so this module bounds the work instead:

1. Common leading and trailing lines are matched in linear time.
2. The rest goes through Myers' O((N+M)·D) greedy algorithm, which finds a shortest edit
   script. It stops once it has spent ``DIFF_WORK_BUDGET`` steps.
3. Past the budget, the unmatched middle is reported as deleted, then inserted. That is still a
   correct diff (applying it turns the old text into the new one), just not a minimal one.

The unified text is built from the same opcodes, so it never runs ``difflib`` either.
"""

from __future__ import annotations

from array import array
from collections.abc import Iterator, Sequence
from itertools import pairwise
from math import isqrt
from typing import Literal

from app.schemas import DiffLine, TextDiff

# Steps (diagonal moves, snake comparisons and trace copies) Myers may spend on one text:
# about 0.25 s of CPU in the worst case. Ordinary edits use a tiny fraction of it.
DIFF_WORK_BUDGET = 1_000_000
UNIFIED_CONTEXT = 3

OpTag = Literal["equal", "delete", "insert", "replace"]
Opcode = tuple[OpTag, int, int, int, int]


def _intern_lines(a: Sequence[str], b: Sequence[str]) -> tuple[list[int], list[int]]:
    """Map lines to small integers so comparisons are cheap."""
    ids: dict[str, int] = {}
    return (
        [ids.setdefault(line, len(ids)) for line in a],
        [ids.setdefault(line, len(ids)) for line in b],
    )


def _myers_path(a: Sequence[int], b: Sequence[int], budget: int) -> list[tuple[int, int]] | None:
    """A shortest edit path from ``(0, 0)`` to ``(len(a), len(b))``, or ``None`` over budget.

    Consecutive points of the path are joined either by a diagonal run (equal lines) or by a
    single edit (one deleted or inserted line); :func:`_path_opcodes` turns them into opcodes.
    """
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return [(0, 0), (n, m)]
    # (D + 1)^2 frontier steps are spent by depth D, so the budget caps the depth too.
    max_d = min(n + m, isqrt(budget) + 1)
    offset = max_d + 1
    v = [0] * (2 * max_d + 3)
    trace: list[array[int]] = []
    spent = 0
    for d in range(max_d + 1):
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and v[offset + k - 1] < v[offset + k + 1]):
                x = v[offset + k + 1]  # move down: insert b[y - 1]
            else:
                x = v[offset + k - 1] + 1  # move right: delete a[x - 1]
            y = x - k
            start = x
            while x < n and y < m and a[x] == b[y]:
                x += 1
                y += 1
            v[offset + k] = x
            if x >= n and y >= m:
                return _backtrack(trace, d, n, m)
            spent += 1 + x - start
            if spent > budget:
                return None
        spent += 2 * d + 1
        if spent > budget:
            return None
        # The furthest x per diagonal k in [-d, d] after d edits, for backtracking.
        trace.append(array("i", v[offset - d : offset + d + 1]))
    # Unreachable: either max_d = n + m and the path ends by then, or max_d is the budget cap
    # and the budget runs out first.
    return None  # pragma: no cover


def _backtrack(trace: list[array[int]], depth: int, n: int, m: int) -> list[tuple[int, int]]:
    """Walk the stored frontiers back from ``(n, m)``; see :func:`_myers_path`."""
    points: list[tuple[int, int]] = [(n, m)]
    x, y = n, m
    for d in range(depth, 0, -1):
        frontier = trace[d - 1]  # diagonals k in [-(d - 1), d - 1], stored at k + d - 1
        k = x - y
        if k == -d or (k != d and frontier[k - 1 + d - 1] < frontier[k + 1 + d - 1]):
            prev_k = k + 1
            prev_x = frontier[prev_k + d - 1]
            mid = (prev_x, prev_x - prev_k + 1)  # after inserting b[prev_y]
        else:
            prev_k = k - 1
            prev_x = frontier[prev_k + d - 1]
            mid = (prev_x + 1, prev_x - prev_k)  # after deleting a[prev_x]
        points.append(mid)
        x, y = prev_x, prev_x - prev_k
        points.append((x, y))
    points.append((0, 0))
    points.reverse()
    return points


def _path_opcodes(points: list[tuple[int, int]], i0: int, j0: int) -> list[Opcode]:
    """Opcodes (offset by ``i0``/``j0``) for a path of diagonal runs and single edits."""
    codes: list[Opcode] = []
    for (x1, y1), (x2, y2) in pairwise(points):
        if (x1, y1) == (x2, y2):
            continue
        if x2 - x1 == y2 - y1:
            _append(codes, "equal", x1 + i0, x2 + i0, y1 + j0, y2 + j0)
        else:
            _append(codes, "replace", x1 + i0, x2 + i0, y1 + j0, y2 + j0)
    return codes


def _append(codes: list[Opcode], tag: OpTag, i1: int, i2: int, j1: int, j2: int) -> None:
    """Append an opcode, merging it into the previous one when both are equal or both changes.

    A change is classified as ``insert``, ``delete`` or ``replace`` from its ranges.
    """
    if i1 == i2 and j1 == j2:
        return
    if codes and (codes[-1][0] == "equal") == (tag == "equal"):
        _, i1, _, j1, _ = codes.pop()
    if tag != "equal":
        tag = "insert" if i1 == i2 else "delete" if j1 == j2 else "replace"
    codes.append((tag, i1, i2, j1, j2))


def line_opcodes(
    a: Sequence[str], b: Sequence[str], budget: int = DIFF_WORK_BUDGET
) -> list[Opcode]:
    """``difflib``-style opcodes turning ``a`` into ``b``, computed in bounded time."""
    n, m = len(a), len(b)
    prefix = 0
    while prefix < n and prefix < m and a[prefix] == b[prefix]:
        prefix += 1
    suffix = 0
    while suffix < n - prefix and suffix < m - prefix and a[n - 1 - suffix] == b[m - 1 - suffix]:
        suffix += 1
    codes: list[Opcode] = []
    if prefix:
        _append(codes, "equal", 0, prefix, 0, prefix)
    a_mid, b_mid = _intern_lines(a[prefix : n - suffix], b[prefix : m - suffix])
    points = _myers_path(a_mid, b_mid, budget)
    if points is None:  # over budget: report the whole middle as replaced
        _append(codes, "replace", prefix, n - suffix, prefix, m - suffix)
    else:
        for code in _path_opcodes(points, prefix, prefix):
            _append(codes, *code)
    if suffix:
        _append(codes, "equal", n - suffix, n, m - suffix, m)
    return codes


def _grouped(codes: list[Opcode], context: int) -> Iterator[list[Opcode]]:
    """Hunks with ``context`` equal lines around each change (as ``difflib`` groups them)."""
    if codes and codes[0][0] == "equal":
        tag, i1, i2, j1, j2 = codes[0]
        codes = [(tag, max(i1, i2 - context), i2, max(j1, j2 - context), j2), *codes[1:]]
    if codes and codes[-1][0] == "equal":
        tag, i1, i2, j1, j2 = codes[-1]
        codes = [*codes[:-1], (tag, i1, min(i2, i1 + context), j1, min(j2, j1 + context))]
    group: list[Opcode] = []
    for tag, i1, i2, j1, j2 in codes:
        if tag == "equal" and i2 - i1 > 2 * context:
            group.append((tag, i1, min(i2, i1 + context), j1, min(j2, j1 + context)))
            yield group
            group = []
            i1, j1 = max(i1, i2 - context), max(j1, j2 - context)
        group.append((tag, i1, i2, j1, j2))
    if group and not (len(group) == 1 and group[0][0] == "equal"):
        yield group


def _range(start: int, stop: int) -> str:
    """A unified-diff hunk range (``start`` is 0-based)."""
    length = stop - start
    if length == 1:
        return str(start + 1)
    return f"{start + 1 if length else start},{length}"


def unified_text(
    a: Sequence[str], b: Sequence[str], codes: list[Opcode], from_label: str, to_label: str
) -> str:
    """Unified diff (no trailing newlines) in the same format as ``difflib.unified_diff``."""
    out: list[str] = []
    for group in _grouped(codes, UNIFIED_CONTEXT):
        if not out:
            out += [f"--- {from_label}", f"+++ {to_label}"]
        first, last = group[0], group[-1]
        out.append(f"@@ -{_range(first[1], last[2])} +{_range(first[3], last[4])} @@")
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                out.extend(" " + line for line in a[i1:i2])
                continue
            out.extend("-" + line for line in a[i1:i2])
            out.extend("+" + line for line in b[j1:j2])
    return "\n".join(out)


def diff_text(old: str | None, new: str | None, from_version: int, to_version: int) -> TextDiff:
    """Line diff of two texts (``None`` is treated as empty). Line numbers are 1-based."""
    a = (old or "").splitlines()
    b = (new or "").splitlines()
    codes = line_opcodes(a, b)
    lines: list[DiffLine] = []
    for tag, i1, i2, j1, j2 in codes:
        if tag == "equal":
            lines.extend(
                DiffLine(op="equal", old_line=i + 1, new_line=j + 1, text=a[i])
                for i, j in zip(range(i1, i2), range(j1, j2), strict=True)
            )
            continue
        lines.extend(
            DiffLine(op="delete", old_line=i + 1, new_line=None, text=a[i]) for i in range(i1, i2)
        )
        lines.extend(
            DiffLine(op="insert", old_line=None, new_line=j + 1, text=b[j]) for j in range(j1, j2)
        )
    added = sum(1 for line in lines if line.op == "insert")
    removed = sum(1 for line in lines if line.op == "delete")
    return TextDiff(
        changed=added + removed > 0,
        added=added,
        removed=removed,
        unified=unified_text(a, b, codes, f"v{from_version}", f"v{to_version}"),
        lines=lines,
    )
