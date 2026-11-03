import type { DiffLine, TextDiff } from "../api/types";
import { cn } from "../lib/cn";
import { pairDiffLines, type DiffRow } from "../lib/diff";
import { Badge } from "./ui/Badge";
import { HorizontalScroll } from "./ui/HorizontalScroll";

export interface DiffViewProps {
  title: string;
  diff: TextDiff;
  fromLabel: string;
  toLabel: string;
}

function Cell({ line, side }: { line: DiffLine | null; side: "left" | "right" }) {
  if (!line) {
    return (
      <>
        <td className="w-10 border-r border-line bg-surface-muted/60 px-2 text-right select-none" />
        <td className="bg-surface-muted/60" />
      </>
    );
  }
  const changed = line.op !== "equal";
  const removed = side === "left" && line.op === "delete";
  const added = side === "right" && line.op === "insert";
  const number = side === "left" ? line.old_line : line.new_line;
  return (
    <>
      <td
        className={cn(
          "w-10 border-r border-line px-2 text-right align-top text-fg-muted tabular-nums select-none",
          removed && "bg-danger-soft",
          added && "bg-success-soft",
        )}
      >
        {number ?? ""}
      </td>
      <td
        className={cn(
          "px-2 align-top break-words whitespace-pre-wrap",
          removed && "bg-danger-soft text-fg",
          added && "bg-success-soft text-fg",
        )}
      >
        {changed ? (
          <>
            <span aria-hidden="true" className={cn("mr-1 font-bold", removed ? "text-danger" : "text-success")}>
              {removed ? "-" : "+"}
            </span>
            <span className="sr-only">{removed ? "removed: " : "added: "}</span>
          </>
        ) : (
          <span aria-hidden="true" className="mr-1 text-transparent">
            {" "}
          </span>
        )}
        {line.text || " "}
      </td>
    </>
  );
}

function rowKey(row: DiffRow, index: number): string {
  return `${index}-${row.left?.old_line ?? "x"}-${row.right?.new_line ?? "x"}`;
}

/**
 * Side-by-side diff of one text field (left = old version, right = new).
 * Changes are marked with color plus -/+ glyphs and screen-reader text.
 */
export function DiffView({ title, diff, fromLabel, toLabel }: DiffViewProps) {
  const rows = pairDiffLines(diff.lines);
  return (
    <section aria-label={`${title} diff`} className="min-w-0 rounded-lg border border-line bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {diff.changed ? (
          <span className="flex gap-2 text-xs">
            <Badge tone="success">+{diff.added} added</Badge>
            <Badge tone="danger">-{diff.removed} removed</Badge>
          </span>
        ) : (
          <Badge>No changes</Badge>
        )}
      </div>
      {rows.length === 0 ? (
        <p className="px-3 py-3 text-sm text-fg-muted">Empty in both versions.</p>
      ) : (
        <HorizontalScroll label={`${title} diff`}>
          <table className="w-full min-w-[36rem] table-fixed border-collapse font-mono text-xs leading-relaxed">
            <caption className="sr-only">
              {title}: {fromLabel} on the left, {toLabel} on the right
            </caption>
            <thead>
              <tr className="border-b border-line bg-surface-muted text-left text-fg-muted">
                <th scope="col" className="w-10 px-2 py-1 font-medium">
                  <span className="sr-only">{fromLabel} line</span>
                </th>
                <th scope="col" className="px-2 py-1 font-sans font-medium">
                  {fromLabel}
                </th>
                <th scope="col" className="w-10 px-2 py-1 font-medium">
                  <span className="sr-only">{toLabel} line</span>
                </th>
                <th scope="col" className="px-2 py-1 font-sans font-medium">
                  {toLabel}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={rowKey(row, index)} className="border-b border-line/60 last:border-b-0">
                  <Cell line={row.left} side="left" />
                  <Cell line={row.right} side="right" />
                </tr>
              ))}
            </tbody>
          </table>
        </HorizontalScroll>
      )}
    </section>
  );
}
