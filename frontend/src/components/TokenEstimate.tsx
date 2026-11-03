import type { TokenEstimate as TokenEstimateData } from "../api/types";
import { formatNumber, formatTokens } from "../lib/format";
import { Tooltip } from "./ui/Tooltip";

export interface TokenEstimateProps {
  estimate: TokenEstimateData | undefined;
  pending: boolean;
  error: unknown;
}

/** Input token estimate: `~N tokens` (heuristic) or `N tokens` (exact Anthropic count), with a method tooltip. */
export function TokenEstimate({ estimate, pending, error }: TokenEstimateProps) {
  if (!estimate) {
    return (
      <p className="text-xs text-fg-muted" aria-live="polite">
        {pending ? "Estimating tokens…" : error ? "Token estimate unavailable" : "Type a prompt to estimate tokens"}
      </p>
    );
  }
  const exact = estimate.method === "anthropic_count_tokens";
  const label = `${exact ? "" : "~"}${formatTokens(estimate.input_tokens)} tokens`;
  const method = exact
    ? "Exact count from the Anthropic token counting API."
    : "Heuristic estimate (about 4 characters per token).";
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-muted" aria-live="polite">
      <Tooltip content={method}>
        {(tooltipId) => (
          <span
            tabIndex={0}
            aria-describedby={tooltipId}
            className="cursor-help rounded font-medium text-fg underline decoration-dotted underline-offset-2"
          >
            {label}
          </span>
        )}
      </Tooltip>
      <span>
        {formatNumber(estimate.characters)} characters · {formatNumber(estimate.words)} words
      </span>
      {pending ? <span>updating…</span> : null}
      {estimate.warnings.map((warning) => (
        <span key={warning} className="text-warning">
          {warning}
        </span>
      ))}
    </div>
  );
}
