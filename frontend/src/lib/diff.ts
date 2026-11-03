/** Side-by-side pairing of server diff lines (contract section 8.5). */
import type { DiffLine } from "../api/types";

export type DiffRowKind = "equal" | "change" | "delete" | "insert";

export interface DiffRow {
  kind: DiffRowKind;
  left: DiffLine | null;
  right: DiffLine | null;
}

/**
 * Pairs diff lines into rows: `equal` lines appear on both sides; a run of
 * deletes followed by a run of inserts is paired index by index (the shorter
 * side padded with empty cells); lone deletes are left-only and lone inserts
 * right-only.
 */
export function pairDiffLines(lines: readonly DiffLine[]): DiffRow[] {
  const rows: DiffRow[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line === undefined) break;
    if (line.op === "equal") {
      rows.push({ kind: "equal", left: line, right: line });
      i += 1;
      continue;
    }
    const deletes: DiffLine[] = [];
    for (let next = lines[i]; next?.op === "delete"; next = lines[i]) {
      deletes.push(next);
      i += 1;
    }
    const inserts: DiffLine[] = [];
    for (let next = lines[i]; next?.op === "insert"; next = lines[i]) {
      inserts.push(next);
      i += 1;
    }
    const count = Math.max(deletes.length, inserts.length);
    for (let k = 0; k < count; k += 1) {
      const left = deletes[k] ?? null;
      const right = inserts[k] ?? null;
      rows.push({ kind: left && right ? "change" : left ? "delete" : "insert", left, right });
    }
  }
  return rows;
}
