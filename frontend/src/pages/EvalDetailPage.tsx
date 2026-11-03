import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, ChevronLeft, CircleCheck, CircleDashed, CircleX, Trash2, TriangleAlert } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError } from "../api/client";
import { cancelEval, deleteEval, getEval } from "../api/endpoints";
import { queryKeys } from "../api/queryKeys";
import type { CaseResultStatus, EvalCaseSnapshot, EvalResult, EvalRunDetail, ModelInfo } from "../api/types";
import { Markdown } from "../components/Markdown";
import { PageHeader } from "../components/PageHeader";
import { PassRateBar } from "../components/PassRateBar";
import { StatusBadge } from "../components/StatusBadge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { Dialog } from "../components/ui/Dialog";
import { ErrorState } from "../components/ui/ErrorState";
import { HorizontalScroll } from "../components/ui/HorizontalScroll";
import { PageSkeleton } from "../components/ui/Skeleton";
import { SegmentedControl } from "../components/ui/Tabs";
import { useToast } from "../context/toast";
import { useModels } from "../hooks/queries";
import { assertionLabel } from "../lib/assertions";
import { cn } from "../lib/cn";
import { formatCost, formatDateTime, formatLatency, formatPercent, formatRelativeTime, formatTokens } from "../lib/format";
import { modelName } from "../lib/models";

/** Poll interval while an evaluation is queued or running (contract section 8.4). */
export const EVAL_POLL_INTERVAL_MS = 1500;

const isActive = (status: EvalRunDetail["status"]) => status === "queued" || status === "running";

/** Evaluation detail: live progress, per-model summaries and the case x model results matrix. */
export default function EvalDetailPage() {
  const { evalId = "" } = useParams();
  const run = useQuery({
    queryKey: queryKeys.eval(evalId),
    queryFn: ({ signal }) => getEval(evalId, signal),
    refetchInterval: (query) => (query.state.data && isActive(query.state.data.status) ? EVAL_POLL_INTERVAL_MS : false),
  });

  if (run.isPending) {
    return (
      <>
        <PageHeader title="Evaluation" eyebrow={<BackLink />} />
        <PageSkeleton />
      </>
    );
  }
  if (run.isError) {
    const notFound = run.error instanceof ApiError && run.error.status === 404;
    return (
      <>
        <PageHeader title={notFound ? "Evaluation not found" : "Evaluation"} eyebrow={<BackLink />} />
        <ErrorState error={run.error} onRetry={notFound ? undefined : () => void run.refetch()} />
      </>
    );
  }
  return <EvalView run={run.data} />;
}

function BackLink() {
  return (
    <Link to="/evals" className="inline-flex items-center gap-1 text-accent-text underline-offset-2 hover:underline">
      <ChevronLeft aria-hidden="true" className="size-4" />
      Evaluations
    </Link>
  );
}

const CELL_STATUS: Record<CaseResultStatus, { label: string; icon: ReactNode; className: string }> = {
  passed: { label: "Passed", icon: <CircleCheck aria-hidden="true" className="size-4" />, className: "text-success" },
  failed: { label: "Failed", icon: <CircleX aria-hidden="true" className="size-4" />, className: "text-danger" },
  error: { label: "Error", icon: <TriangleAlert aria-hidden="true" className="size-4" />, className: "text-warning" },
  pending: { label: "Pending", icon: <CircleDashed aria-hidden="true" className="size-4" />, className: "text-fg-muted" },
};

function EvalView({ run }: { run: EvalRunDetail }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { toast } = useToast();
  const models = useModels();
  const [open, setOpen] = useState<{ caseIndex: number; model: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const catalog = models.data?.models;

  const cancel = useMutation({
    mutationFn: () => cancelEval(run.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.eval(run.id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.evals() });
      toast({ tone: "info", title: "Evaluation cancelled" });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "eval_not_running") {
        void queryClient.invalidateQueries({ queryKey: queryKeys.eval(run.id) });
        toast({ tone: "info", title: "The evaluation already finished." });
      }
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteEval(run.id),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: queryKeys.eval(run.id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.evals() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.suites() });
      toast({ tone: "success", title: "Evaluation deleted" });
      void navigate("/evals");
    },
  });

  const results = new Map<string, EvalResult>();
  for (const result of run.results) results.set(`${result.case_index}:${result.model}`, result);
  const active = isActive(run.status);
  const percent = run.progress.total === 0 ? 0 : Math.round((run.progress.completed / run.progress.total) * 100);
  const openResult = open ? results.get(`${open.caseIndex}:${open.model}`) : undefined;
  const openCase = open ? run.cases.find((item) => item.index === open.caseIndex) : undefined;

  return (
    <>
      <PageHeader
        title={`${run.suite_name}: ${run.prompt_label}`}
        documentTitle="Evaluation"
        eyebrow={<BackLink />}
        description={`Started ${formatRelativeTime(run.created_at)} with ${run.models.length} ${run.models.length === 1 ? "model" : "models"}.`}
        actions={
          <>
            {active ? (
              <Button icon={<Ban aria-hidden="true" className="size-4" />} loading={cancel.isPending} onClick={() => cancel.mutate()}>
                Cancel
              </Button>
            ) : null}
            <Button variant="danger" icon={<Trash2 aria-hidden="true" className="size-4" />} onClick={() => setConfirmDelete(true)}>
              Delete
            </Button>
          </>
        }
      />

      <div className="space-y-6">
        <Card title="Progress">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <StatusBadge status={run.status} />
              <span className="text-sm text-fg-muted">
                {run.progress.completed} of {run.progress.total} results
              </span>
              <PassRateBar rate={run.pass_rate} />
            </div>
            <div
              role="progressbar"
              aria-label="Evaluation progress"
              aria-valuemin={0}
              aria-valuemax={run.progress.total}
              aria-valuenow={run.progress.completed}
              aria-valuetext={`${run.progress.completed} of ${run.progress.total} complete`}
              className="h-2.5 w-full overflow-hidden rounded-full bg-surface-muted"
            >
              <div className={cn("h-full rounded-full transition-[width]", active ? "bg-info" : "bg-success")} style={{ width: `${percent}%` }} />
            </div>
            <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <div>
                <dt className="text-xs text-fg-muted">Passed</dt>
                <dd className="font-medium text-success">{run.passed}</dd>
              </div>
              <div>
                <dt className="text-xs text-fg-muted">Failed</dt>
                <dd className="font-medium text-danger">{run.failed}</dd>
              </div>
              <div>
                <dt className="text-xs text-fg-muted">Errored</dt>
                <dd className="font-medium text-warning">{run.errored}</dd>
              </div>
              <div>
                <dt className="text-xs text-fg-muted">Judge model</dt>
                <dd className="truncate font-medium">{modelName(catalog, run.judge_model)}</dd>
              </div>
            </dl>
            {run.finished_at ? (
              <p className="text-xs text-fg-muted" title={formatDateTime(run.finished_at)}>
                Finished {formatRelativeTime(run.finished_at)}
              </p>
            ) : null}
            {run.error ? (
              <div role="alert" className="rounded-md border border-danger/40 bg-danger-soft px-3 py-2 text-sm">
                <span className="font-medium text-danger">{run.error.code}: </span>
                {run.error.message}
              </div>
            ) : null}
          </div>
        </Card>

        <section aria-labelledby="per-model-heading">
          <h2 id="per-model-heading" className="mb-3 text-base font-semibold">
            Per model
          </h2>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {run.per_model.map((summary) => (
              <div key={summary.model} className="rounded-lg border border-line bg-surface p-4">
                <h3 className="truncate font-medium">{modelName(catalog, summary.model)}</h3>
                <PassRateBar rate={summary.pass_rate} className="mt-2" />
                <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                  <dt className="text-fg-muted">Passed / failed / errored</dt>
                  <dd className="text-right font-medium tabular-nums">
                    {summary.passed} / {summary.failed} / {summary.errored}
                  </dd>
                  <dt className="text-fg-muted">Pending</dt>
                  <dd className="text-right font-medium tabular-nums">{summary.pending}</dd>
                  <dt className="text-fg-muted">Avg latency</dt>
                  <dd className="text-right font-medium">{formatLatency(summary.avg_latency_ms)}</dd>
                  <dt className="text-fg-muted">Tokens in / out</dt>
                  <dd className="text-right font-medium tabular-nums">
                    {formatTokens(summary.total_input_tokens)} / {formatTokens(summary.total_output_tokens)}
                  </dd>
                  <dt className="text-fg-muted">Cost</dt>
                  <dd className="text-right font-medium">{formatCost(summary.total_cost_usd)}</dd>
                </dl>
              </div>
            ))}
          </div>
        </section>

        <section aria-labelledby="results-heading" className="min-w-0 rounded-lg border border-line bg-surface">
          <h2 id="results-heading" className="border-b border-line px-4 py-3 text-base font-semibold">
            Results
          </h2>
          <HorizontalScroll>
            <table className="w-full min-w-[36rem] text-sm">
              <caption className="sr-only">Results by case (rows) and model (columns). Select a cell for details.</caption>
              <thead className="bg-surface-muted text-left text-xs text-fg-muted">
                <tr>
                  <th scope="col" className="px-4 py-2 font-medium">
                    Case
                  </th>
                  {run.models.map((model) => (
                    <th key={model} scope="col" className="px-4 py-2 font-medium">
                      {modelName(catalog, model)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {run.cases.map((testCase) => (
                  <tr key={testCase.index}>
                    <th scope="row" className="px-4 py-2 text-left font-medium">
                      {testCase.name}
                    </th>
                    {run.models.map((model) => {
                      const result = results.get(`${testCase.index}:${model}`);
                      const status = CELL_STATUS[result?.status ?? "pending"];
                      return (
                        <td key={model} className="px-2 py-1.5">
                          <button
                            type="button"
                            disabled={!result}
                            aria-label={`${testCase.name}, ${modelName(catalog, model)}: ${status.label}${
                              result?.score !== null && result?.score !== undefined ? `, score ${formatPercent(result.score)}` : ""
                            }. Show details`}
                            onClick={() => setOpen({ caseIndex: testCase.index, model })}
                            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-surface-muted disabled:cursor-default"
                          >
                            <span className={cn("inline-flex items-center gap-1.5 font-medium", status.className)}>
                              {status.icon}
                              {status.label}
                            </span>
                            {result?.score !== null && result?.score !== undefined ? (
                              <span className="text-xs text-fg-muted tabular-nums">{formatPercent(result.score)}</span>
                            ) : null}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </HorizontalScroll>
        </section>
      </div>

      {open && openResult && openCase ? (
        <ResultDrawer result={openResult} testCase={openCase} catalog={catalog} onClose={() => setOpen(null)} />
      ) : null}
      <ConfirmDialog
        open={confirmDelete}
        title="Delete this evaluation?"
        message={active ? "The run is still in progress; it will be cancelled and deleted." : "The run and all its results will be deleted."}
        confirmLabel="Delete evaluation"
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

/** Side drawer with one result: variables, output and each assertion outcome. */
function ResultDrawer({
  result,
  testCase,
  catalog,
  onClose,
}: {
  result: EvalResult;
  testCase: EvalCaseSnapshot;
  catalog: ModelInfo[] | undefined;
  onClose: () => void;
}) {
  const [mode, setMode] = useState<"preview" | "raw">("preview");
  const variables = Object.entries(testCase.variables);
  return (
    <Dialog
      open
      variant="drawer"
      onClose={onClose}
      title={testCase.name}
      description={`${modelName(catalog, result.model)} · ${CELL_STATUS[result.status].label}`}
    >
      <div className="space-y-5">
        <section>
          <h3 className="mb-2 text-sm font-semibold">Variables</h3>
          {variables.length === 0 ? (
            <p className="text-sm text-fg-muted">None</p>
          ) : (
            <dl className="space-y-1 text-sm">
              {variables.map(([key, value]) => (
                <div key={key} className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-2">
                  <dt className="truncate font-mono text-xs text-fg-muted">{key}</dt>
                  <dd className="break-words whitespace-pre-wrap">{value}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>

        <section>
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">Output</h3>
            <SegmentedControl
              label="Output format"
              value={mode}
              onChange={setMode}
              options={[
                { value: "preview", label: "Preview" },
                { value: "raw", label: "Raw" },
              ]}
            />
          </div>
          {result.output === null ? (
            <p className="text-sm text-fg-muted">No output.</p>
          ) : mode === "preview" ? (
            <div className="rounded-md border border-line p-3">
              <Markdown>{result.output}</Markdown>
            </div>
          ) : (
            <pre className="rounded-md border border-line bg-surface-muted p-3 font-mono text-xs whitespace-pre-wrap">{result.output}</pre>
          )}
          <p className="mt-2 text-xs text-fg-muted">
            {formatLatency(result.latency_ms)} · {formatTokens(result.input_tokens)} → {formatTokens(result.output_tokens)} tokens ·{" "}
            {formatCost(result.cost_usd)}
          </p>
        </section>

        {result.error ? (
          <div role="alert" className="rounded-md border border-danger/40 bg-danger-soft px-3 py-2 text-sm">
            <span className="font-medium text-danger">{result.error.code}: </span>
            {result.error.message}
          </div>
        ) : null}

        <section>
          <h3 className="mb-2 text-sm font-semibold">Assertions</h3>
          {result.assertions.length === 0 ? (
            <p className="text-sm text-fg-muted">{result.status === "pending" ? "Not evaluated yet." : "No assertion results."}</p>
          ) : (
            <ol className="space-y-2">
              {result.assertions.map((assertion, index) => (
                <li key={`${assertion.type}-${index}`} className="rounded-md border border-line p-3 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">
                      {index + 1}. {assertionLabel(assertion.type)}
                    </span>
                    <span className={cn("inline-flex items-center gap-1 font-medium", assertion.passed ? "text-success" : "text-danger")}>
                      {assertion.passed ? <CircleCheck aria-hidden="true" className="size-4" /> : <CircleX aria-hidden="true" className="size-4" />}
                      {assertion.passed ? "Passed" : "Failed"}
                    </span>
                  </div>
                  <p className="mt-1 break-words text-fg-muted">{assertion.detail}</p>
                  {assertion.score !== null ? <p className="mt-1 text-xs">Score: {assertion.score}/5</p> : null}
                  {assertion.error ? <p className="mt-1 text-xs font-medium text-danger">{assertion.error}</p> : null}
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
    </Dialog>
  );
}
