import { CircleStop, Sparkles } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { ApiError } from "../api/client";
import type { StreamPhase } from "../hooks/useRunStream";
import { cn } from "../lib/cn";
import { CopyButton } from "./CopyButton";
import { Markdown } from "./Markdown";
import { Badge } from "./ui/Badge";
import { ErrorState } from "./ui/ErrorState";
import { Spinner } from "./ui/Spinner";
import { SegmentedControl } from "./ui/Tabs";

export interface OutputPanelProps {
  phase: StreamPhase;
  text: string;
  thinking: string;
  warnings: readonly string[];
  error: ApiError | null;
  /** Rendered under the output (metrics bar). */
  footer?: ReactNode;
  /** Shown before the first run. */
  emptyHint?: ReactNode;
  /** Screen reader announcement when the run finishes (default "Run finished."). */
  doneMessage?: string;
}

/** Short phase announcement for the polite status region (errors use their own alert). */
function phaseMessage(phase: StreamPhase, doneMessage: string | undefined): string {
  switch (phase) {
    case "streaming":
      return "Streaming the answer…";
    case "done":
      return doneMessage ?? "Run finished.";
    case "stopped":
      return "Run stopped.";
    case "idle":
    case "error":
      return "";
  }
}

type ViewMode = "preview" | "raw";

/** Model output region: live Markdown/raw text, thinking, warnings, errors, a copy button and run status announcements. */
export function OutputPanel({ phase, text, thinking, warnings, error, footer, emptyHint, doneMessage }: OutputPanelProps) {
  const [mode, setMode] = useState<ViewMode>("preview");
  const hasOutput = text.length > 0;

  return (
    <section
      aria-label="Model output"
      aria-busy={phase === "streaming"}
      className="flex min-w-0 flex-col rounded-lg border border-line bg-surface shadow-xs"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-semibold">Output</h2>
          {phase === "streaming" ? (
            <Badge tone="info" icon={<Spinner size="xs" />}>
              Streaming
            </Badge>
          ) : null}
          {phase === "stopped" ? (
            <Badge tone="warning" icon={<CircleStop aria-hidden="true" className="size-3.5" />}>
              Stopped
            </Badge>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <SegmentedControl<ViewMode>
            label="Output format"
            value={mode}
            onChange={setMode}
            options={[
              { value: "preview", label: "Preview" },
              { value: "raw", label: "Raw" },
            ]}
          />
          <CopyButton text={text} label="Copy output" disabled={!hasOutput} />
        </div>
      </div>

      <div className="min-h-40 space-y-4 px-4 py-4">
        {thinking ? (
          <details className="rounded-md border border-line bg-surface-muted" open={phase === "streaming" && !hasOutput}>
            <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-fg-muted">Thinking</summary>
            <div className="border-t border-line px-3 py-2 font-mono text-xs leading-relaxed whitespace-pre-wrap text-fg-muted">
              {thinking}
            </div>
          </details>
        ) : null}

        {warnings.length > 0 ? (
          <ul className="space-y-1 rounded-md border border-warning/40 bg-warning-soft px-3 py-2 text-sm text-fg">
            {warnings.map((warning) => (
              <li key={warning}>
                <span className="font-medium text-warning">Warning: </span>
                {warning}
              </li>
            ))}
          </ul>
        ) : null}

        {hasOutput ? (
          mode === "preview" ? (
            <Markdown>{text}</Markdown>
          ) : (
            <pre className="font-mono text-[13px] leading-relaxed break-words whitespace-pre-wrap text-fg">{text}</pre>
          )
        ) : phase === "streaming" ? (
          <p className="text-sm text-fg-muted">Waiting for the first tokens…</p>
        ) : phase === "idle" ? (
          <div className={cn("flex items-start gap-2 text-sm text-fg-muted")}>
            <Sparkles aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <div>{emptyHint ?? "Run the prompt to see the model output here."}</div>
          </div>
        ) : phase === "stopped" ? (
          <p className="text-sm text-fg-muted">Stopped before any output arrived.</p>
        ) : phase === "done" ? (
          <p className="text-sm text-fg-muted">The model returned an empty response.</p>
        ) : null}

        {error ? <ErrorState error={error} title="The run failed" /> : null}
      </div>

      {footer ? <div className="border-t border-line px-4 py-3">{footer}</div> : null}
      {/*
        Always rendered, so changes are announced: start, finish and stop of a
        run (WCAG 4.1.3). The streamed text itself is not live, it would be read
        token by token.
      */}
      <p role="status" className="sr-only">
        {phaseMessage(phase, doneMessage)}
      </p>
    </section>
  );
}
