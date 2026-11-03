import { CircleCheck, CircleX, ShieldAlert, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import type { FinishReason, RunResult } from "../api/types";
import { finishReasonLabel, formatCost, formatLatency, formatTokens } from "../lib/format";
import { Badge, type BadgeTone } from "./ui/Badge";

const FINISH: Record<FinishReason, { tone: BadgeTone; icon: ReactNode; note?: string }> = {
  stop: { tone: "success", icon: <CircleCheck aria-hidden="true" className="size-3.5" /> },
  length: {
    tone: "warning",
    icon: <TriangleAlert aria-hidden="true" className="size-3.5" />,
    note: "Output hit the max tokens limit",
  },
  refusal: {
    tone: "danger",
    icon: <CircleX aria-hidden="true" className="size-3.5" />,
    note: "The model declined to answer",
  },
  content_filter: {
    tone: "danger",
    icon: <ShieldAlert aria-hidden="true" className="size-3.5" />,
    note: "The provider filtered the output",
  },
  other: { tone: "neutral", icon: null },
};

/** Badge describing why generation stopped, with an explanatory note for non-normal endings. */
export function FinishReasonBadge({ reason }: { reason: FinishReason }) {
  const config = FINISH[reason];
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <Badge tone={config.tone} icon={config.icon}>
        {finishReasonLabel(reason)}
      </Badge>
      {config.note ? <span className="text-xs text-fg-muted">{config.note}</span> : null}
    </span>
  );
}

export interface RunMetricsProps {
  result: RunResult;
  modelName: string;
  className?: string;
}

/** Metrics bar for a finished run: model, latency, TTFT, tokens, cost and finish reason. */
export function RunMetrics({ result, modelName, className }: RunMetricsProps) {
  const items: Array<{ term: string; value: ReactNode }> = [
    { term: "Model", value: modelName },
    { term: "Latency", value: formatLatency(result.latency_ms) },
    { term: "Time to first token", value: formatLatency(result.ttft_ms) },
    {
      term: "Tokens",
      value: (
        <>
          {formatTokens(result.input_tokens)} <span aria-hidden="true">→</span>
          <span className="sr-only">input, </span> {formatTokens(result.output_tokens)}
          <span className="sr-only"> output</span>
        </>
      ),
    },
    { term: "Cost", value: formatCost(result.cost_usd) },
  ];
  return (
    <section aria-label="Run metrics" className={className}>
      <dl className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
        {items.map((item) => (
          <div key={item.term} className="min-w-0">
            <dt className="text-xs whitespace-nowrap text-fg-muted">{item.term}</dt>
            <dd className="font-medium break-words text-fg tabular-nums">{item.value}</dd>
          </div>
        ))}
        <div className="min-w-0">
          <dt className="text-xs text-fg-muted">Finish reason</dt>
          <dd className="mt-0.5">
            <FinishReasonBadge reason={result.finish_reason} />
          </dd>
        </div>
      </dl>
    </section>
  );
}
