import { describe, expect, it } from "vitest";
import type { DiffLine } from "../api/types";
import { pairDiffLines } from "./diff";

const eq = (oldLine: number, newLine: number, text: string): DiffLine => ({ op: "equal", old_line: oldLine, new_line: newLine, text });
const del = (oldLine: number, text: string): DiffLine => ({ op: "delete", old_line: oldLine, new_line: null, text });
const ins = (newLine: number, text: string): DiffLine => ({ op: "insert", old_line: null, new_line: newLine, text });

describe("pairDiffLines", () => {
  it("puts equal lines on both sides", () => {
    const rows = pairDiffLines([eq(1, 1, "same")]);
    expect(rows).toEqual([{ kind: "equal", left: eq(1, 1, "same"), right: eq(1, 1, "same") }]);
  });

  it("pairs a delete run with the following insert run index by index, padding the shorter side", () => {
    const rows = pairDiffLines([del(1, "a"), del(2, "b"), ins(1, "x"), eq(3, 2, "tail")]);
    expect(rows.map((row) => [row.kind, row.left?.text ?? null, row.right?.text ?? null])).toEqual([
      ["change", "a", "x"],
      ["delete", "b", null],
      ["equal", "tail", "tail"],
    ]);
  });

  it("pads the left side when inserts outnumber deletes", () => {
    const rows = pairDiffLines([del(1, "a"), ins(1, "x"), ins(2, "y")]);
    expect(rows.map((row) => [row.kind, row.left?.text ?? null, row.right?.text ?? null])).toEqual([
      ["change", "a", "x"],
      ["insert", null, "y"],
    ]);
  });

  it("keeps lone inserts on the right and lone deletes on the left", () => {
    const rows = pairDiffLines([eq(1, 1, "a"), ins(2, "new"), eq(2, 3, "b"), del(3, "gone")]);
    expect(rows.map((row) => row.kind)).toEqual(["equal", "insert", "equal", "delete"]);
    expect(rows[1]?.left).toBeNull();
    expect(rows[3]?.right).toBeNull();
  });

  it("returns no rows for an empty diff", () => {
    expect(pairDiffLines([])).toEqual([]);
  });
});
