import { formatPercent } from "../lib/format";

/** Horizontal pass-rate bar; the percentage is always shown as text too. */
export function PassRateBar({ rate, className }: { rate: number | null; className?: string }) {
  const percent = rate === null ? 0 : Math.round(rate * 100);
  return (
    <span className={`flex items-center gap-2 ${className ?? ""}`}>
      <span aria-hidden="true" className="h-2 w-20 overflow-hidden rounded-full bg-surface-muted">
        {/* Width is set through the style property (CSSOM), which the strict CSP allows. */}
        <span className="block h-full rounded-full bg-success" style={{ width: `${percent}%` }} />
      </span>
      <span className="text-xs font-medium tabular-nums">{formatPercent(rate)}</span>
    </span>
  );
}
