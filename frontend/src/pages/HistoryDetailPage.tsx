import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, Play, RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError } from "../api/client";
import { deleteHistoryItem, getHistoryItem } from "../api/endpoints";
import { queryKeys } from "../api/queryKeys";
import type { HistoryDetail } from "../api/types";
import { CopyButton } from "../components/CopyButton";
import { Markdown } from "../components/Markdown";
import { PageHeader } from "../components/PageHeader";
import { ScrollableText } from "../components/ui/ScrollableText";
import { FinishReasonBadge } from "../components/RunMetrics";
import { StatusBadge } from "../components/StatusBadge";
import { Button, ButtonLink } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { ErrorState } from "../components/ui/ErrorState";
import { PageSkeleton } from "../components/ui/Skeleton";
import { SegmentedControl } from "../components/ui/Tabs";
import { useToast } from "../context/toast";
import { useModels } from "../hooks/queries";
import { formatCost, formatDateTime, formatLatency, formatRelativeTime, formatTokens } from "../lib/format";
import { modelName } from "../lib/models";

/** One history entry with every stored field and Open / Re-run / Delete actions. */
export default function HistoryDetailPage() {
  const { historyId = "" } = useParams();
  const item = useQuery({
    queryKey: queryKeys.historyItem(historyId),
    queryFn: ({ signal }) => getHistoryItem(historyId, signal),
  });
  if (item.isPending) {
    return (
      <>
        <PageHeader title="History entry" eyebrow={<BackLink />} />
        <PageSkeleton />
      </>
    );
  }
  if (item.isError) {
    const notFound = item.error instanceof ApiError && item.error.status === 404;
    return (
      <>
        <PageHeader title={notFound ? "History entry not found" : "History entry"} eyebrow={<BackLink />} />
        <ErrorState error={item.error} onRetry={notFound ? undefined : () => void item.refetch()} />
      </>
    );
  }
  return <HistoryView item={item.data} />;
}

function BackLink() {
  return (
    <Link to="/history" className="inline-flex items-center gap-1 text-accent-text underline-offset-2 hover:underline">
      <ChevronLeft aria-hidden="true" className="size-4" />
      History
    </Link>
  );
}

function TextBlock({ label, text }: { label: string; text: string | null }) {
  return (
    <div className="min-w-0">
      <div className="mb-1 flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold tracking-wide text-fg-muted uppercase">{label}</h3>
        {text ? <CopyButton text={text} label={`Copy ${label.toLowerCase()}`} /> : null}
      </div>
      {text ? (
        <ScrollableText label={label} text={text} className="max-h-96" />
      ) : (
        <p className="text-sm text-fg-muted">None</p>
      )}
    </div>
  );
}

function HistoryView({ item }: { item: HistoryDetail }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { toast } = useToast();
  const models = useModels();
  const [mode, setMode] = useState<"preview" | "raw">("preview");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const name = modelName(models.data?.models, item.model);
  const variables = Object.entries(item.variables);

  const remove = useMutation({
    mutationFn: () => deleteHistoryItem(item.id),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: queryKeys.historyItem(item.id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.history() });
      toast({ tone: "success", title: "History entry deleted" });
      void navigate("/history");
    },
  });

  return (
    <>
      <PageHeader
        title={`Run with ${name}`}
        documentTitle="History entry"
        eyebrow={<BackLink />}
        description={
          <span title={formatDateTime(item.created_at)}>
            {formatRelativeTime(item.created_at)} · {item.source === "compare" ? "comparison cell" : "playground run"}
          </span>
        }
        actions={
          <>
            <ButtonLink to={`/playground?history=${item.id}`} icon={<Play aria-hidden="true" className="size-4" />}>
              Open in Playground
            </ButtonLink>
            <ButtonLink
              to={`/playground?history=${item.id}&autorun=1`}
              variant="primary"
              icon={<RotateCcw aria-hidden="true" className="size-4" />}
            >
              Re-run
            </ButtonLink>
            <Button variant="danger" icon={<Trash2 aria-hidden="true" className="size-4" />} onClick={() => setConfirmDelete(true)}>
              Delete
            </Button>
          </>
        }
      />

      <div className="space-y-6">
        <Card title="Summary">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-xs text-fg-muted">Status</dt>
              <dd className="mt-0.5">
                <StatusBadge status={item.status} />
              </dd>
            </div>
            <div>
              <dt className="text-xs text-fg-muted">Finish reason</dt>
              <dd className="mt-0.5">{item.finish_reason ? <FinishReasonBadge reason={item.finish_reason} /> : "-"}</dd>
            </div>
            <div>
              <dt className="text-xs text-fg-muted">Latency / first token</dt>
              <dd className="font-medium">
                {formatLatency(item.latency_ms)} / {formatLatency(item.ttft_ms)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-fg-muted">Tokens in → out</dt>
              <dd className="font-medium tabular-nums">
                {formatTokens(item.input_tokens)} → {formatTokens(item.output_tokens)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-fg-muted">Cost</dt>
              <dd className="font-medium">{formatCost(item.cost_usd)}</dd>
            </div>
            <div>
              <dt className="text-xs text-fg-muted">Temperature</dt>
              <dd className="font-medium">{item.params.temperature ?? "Model default"}</dd>
            </div>
            <div>
              <dt className="text-xs text-fg-muted">Max tokens</dt>
              <dd className="font-medium">{formatTokens(item.params.max_tokens)}</dd>
            </div>
            <div>
              <dt className="text-xs text-fg-muted">Show thinking</dt>
              <dd className="font-medium">{item.params.thinking ? "On" : "Off"}</dd>
            </div>
            {item.request_id ? (
              <div className="col-span-2 min-w-0 sm:col-span-4">
                <dt className="text-xs text-fg-muted">Provider request id</dt>
                <dd className="truncate font-mono text-xs">{item.request_id}</dd>
              </div>
            ) : null}
          </dl>
          {item.error_message ? (
            <div role="alert" className="mt-4 rounded-md border border-danger/40 bg-danger-soft px-3 py-2 text-sm">
              <span className="font-medium text-danger">{item.error_code ?? "error"}: </span>
              {item.error_message}
            </div>
          ) : null}
          {item.warnings.length > 0 ? (
            <ul className="mt-4 space-y-1 rounded-md border border-warning/40 bg-warning-soft px-3 py-2 text-sm">
              {item.warnings.map((warning) => (
                <li key={warning}>
                  <span className="font-medium text-warning">Warning: </span>
                  {warning}
                </li>
              ))}
            </ul>
          ) : null}
        </Card>

        <Card
          title="Output"
          actions={
            <>
              <SegmentedControl
                label="Output format"
                value={mode}
                onChange={setMode}
                options={[
                  { value: "preview", label: "Preview" },
                  { value: "raw", label: "Raw" },
                ]}
              />
              <CopyButton text={item.output} label="Copy output" disabled={!item.output} />
            </>
          }
        >
          {item.thinking ? (
            <details className="mb-4 rounded-md border border-line bg-surface-muted">
              <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-fg-muted">Thinking</summary>
              <div className="border-t border-line px-3 py-2 font-mono text-xs whitespace-pre-wrap text-fg-muted">{item.thinking}</div>
            </details>
          ) : null}
          {item.output ? (
            mode === "preview" ? (
              <Markdown>{item.output}</Markdown>
            ) : (
              <pre className="font-mono text-[13px] whitespace-pre-wrap">{item.output}</pre>
            )
          ) : (
            <p className="text-sm text-fg-muted">No output was produced.</p>
          )}
        </Card>

        <div className="grid min-w-0 gap-6 lg:grid-cols-2">
          <Card title="Templates">
            <div className="space-y-4">
              <TextBlock label="System template" text={item.system_template} />
              <TextBlock label="Prompt template" text={item.prompt_template} />
            </div>
          </Card>
          <Card title="Rendered">
            <div className="space-y-4">
              <TextBlock label="Rendered system" text={item.rendered_system} />
              <TextBlock label="Rendered prompt" text={item.rendered_prompt} />
            </div>
          </Card>
        </div>

        <Card title="Variables">
          {variables.length === 0 ? (
            <p className="text-sm text-fg-muted">No variables were sent.</p>
          ) : (
            <dl className="space-y-2 text-sm">
              {variables.map(([key, value]) => (
                <div key={key} className="grid gap-1 sm:grid-cols-[12rem_minmax(0,1fr)]">
                  <dt className="font-mono text-xs text-fg-muted">{key}</dt>
                  <dd className="break-words whitespace-pre-wrap">{value}</dd>
                </div>
              ))}
            </dl>
          )}
        </Card>
      </div>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete this history entry?"
        message="The stored prompt and output of this run will be removed."
        confirmLabel="Delete entry"
        danger
        pending={remove.isPending}
        error={remove.error ? <ErrorState error={remove.error} compact /> : undefined}
        onConfirm={() => remove.mutate()}
        onCancel={() => {
          remove.reset();
          setConfirmDelete(false);
        }}
      />
    </>
  );
}
