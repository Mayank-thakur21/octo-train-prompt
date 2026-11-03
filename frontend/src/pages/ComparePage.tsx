import { useQueryClient } from "@tanstack/react-query";
import { Copy, Gauge, Play, Plus, Square, Trash2, Wallet } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import type { CompareCell, CompareRequest, ErrorBody, Limits, ModelInfo, ModelsResponse } from "../api/types";
import { Markdown } from "../components/Markdown";
import { ModelMultiSelect } from "../components/ModelMultiSelect";
import { PageHeader } from "../components/PageHeader";
import { FinishReasonBadge } from "../components/RunMetrics";
import { RunParamsForm } from "../components/RunParamsForm";
import { VariablesForm } from "../components/VariablesForm";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ErrorState } from "../components/ui/ErrorState";
import { HorizontalScroll } from "../components/ui/HorizontalScroll";
import { IconButton } from "../components/ui/IconButton";
import { PageSkeleton, Skeleton } from "../components/ui/Skeleton";
import { TextArea } from "../components/ui/TextArea";
import { TextField } from "../components/ui/TextField";
import { toastForError, useToast } from "../context/toast";
import { useMeta, useModels } from "../hooks/queries";
import { useCompareStream } from "../hooks/useCompareStream";
import { usePersistedDraft } from "../hooks/usePersistedDraft";
import { cn } from "../lib/cn";
import { formatCost, formatLatency, formatTokens } from "../lib/format";
import { combineCapabilities, findModel } from "../lib/models";
import { isRunParamsValue, paramsAreValid, type RunParamsValue } from "../lib/params";
import { isRecord, isStringRecord, readStorage, STORAGE_KEYS } from "../lib/storage";
import { nonEmptyValues, unionVariables } from "../lib/template";

interface VariantDraft {
  key: string;
  label: string;
  system: string;
  prompt: string;
}

interface CompareDraft {
  variants: Array<Omit<VariantDraft, "key">>;
  values: Record<string, string>;
  models: string[];
  params: RunParamsValue;
}

let variantCounter = 0;
function withKey(variant: Omit<VariantDraft, "key">): VariantDraft {
  variantCounter += 1;
  return { ...variant, key: `variant-${variantCounter}` };
}

function isCompareDraft(value: unknown): value is CompareDraft {
  return (
    isRecord(value) &&
    Array.isArray(value.variants) &&
    value.variants.length > 0 &&
    value.variants.every(
      (item) =>
        isRecord(item) && typeof item.label === "string" && typeof item.system === "string" && typeof item.prompt === "string",
    ) &&
    isStringRecord(value.values) &&
    Array.isArray(value.models) &&
    value.models.every((item) => typeof item === "string") &&
    isRunParamsValue(value.params)
  );
}

/** Default label "Variant A", "Variant B", ... (same rule as the backend). */
function defaultLabel(index: number): string {
  return `Variant ${String.fromCharCode(65 + (index % 26))}`;
}

/** Compare route: waits for the catalog and limits, then mounts the editor. */
export default function ComparePage() {
  const meta = useMeta();
  const models = useModels();
  if (meta.error || models.error) {
    return (
      <>
        <PageHeader title="Compare" />
        <ErrorState
          error={meta.error ?? models.error}
          onRetry={() => {
            void meta.refetch();
            void models.refetch();
          }}
        />
      </>
    );
  }
  if (!meta.data || !models.data) {
    return (
      <>
        <PageHeader title="Compare" />
        <PageSkeleton />
      </>
    );
  }
  return <CompareEditor catalog={models.data} limits={meta.data.limits} />;
}

interface RunSnapshot {
  labels: string[];
  models: string[];
}

function CompareEditor({ catalog, limits }: { catalog: ModelsResponse; limits: Limits }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const stream = useCompareStream();
  const [initial] = useState(() => readStorage<CompareDraft | null>(STORAGE_KEYS.compareDraft, null, isCompareDraft));
  const [variants, setVariants] = useState<VariantDraft[]>(() =>
    (initial?.variants ?? [{ label: "", system: "", prompt: "" }])
      .slice(0, limits.max_compare_variants)
      .map(withKey),
  );
  const [values, setValues] = useState<Record<string, string>>(initial?.values ?? {});
  const [selected, setSelected] = useState<string[]>(() => {
    const available = (initial?.models ?? [catalog.default_model]).filter((id) => findModel(catalog.models, id)?.available);
    return available.length > 0 ? available.slice(0, limits.max_compare_models) : [];
  });
  const [params, setParams] = useState<RunParamsValue>(
    initial?.params ?? { temperature: null, maxTokens: null, thinking: false },
  );
  const [snapshot, setSnapshot] = useState<RunSnapshot | null>(null);
  const [submitted, setSubmitted] = useState(false);

  // Persist the draft; a pending change is saved at once when leaving the page.
  const draft = useMemo<CompareDraft>(
    () => ({
      variants: variants.map(({ label, system, prompt }) => ({ label, system, prompt })),
      values,
      models: selected,
      params,
    }),
    [variants, values, selected, params],
  );
  usePersistedDraft(STORAGE_KEYS.compareDraft, draft);

  const variables = useMemo(() => unionVariables(variants), [variants]);
  const selectedModels = selected
    .map((id) => findModel(catalog.models, id))
    .filter((model): model is ModelInfo => model !== undefined);
  const caps = combineCapabilities(selectedModels, limits.max_output_tokens);
  const cellCount = variants.length * selected.length;
  const overCap = cellCount > limits.max_compare_cells;
  const emptyPrompt = variants.some((variant) => !variant.prompt);
  const canRun =
    !stream.isStreaming && selected.length > 0 && !overCap && !emptyPrompt && paramsAreValid(params, caps.maxOutputTokens);

  const updateVariant = (key: string, patch: Partial<VariantDraft>) =>
    setVariants((current) => current.map((variant) => (variant.key === key ? { ...variant, ...patch } : variant)));

  const run = async () => {
    setSubmitted(true);
    if (!canRun) return;
    const labels = variants.map((variant, index) => variant.label.trim() || defaultLabel(index));
    setSnapshot({ labels, models: [...selected] });
    const req: CompareRequest = {
      variants: variants.map((variant) => ({
        label: variant.label.trim() || null,
        system: variant.system || null,
        prompt: variant.prompt,
      })),
      models: selected,
      variables: nonEmptyValues(
        values,
        variables.map((item) => item.name),
      ),
      temperature: caps.supportsTemperature ? params.temperature : null,
      max_tokens: params.maxTokens,
      thinking: caps.supportsThinking && params.thinking,
    };
    const outcome = await stream.run(req);
    if (outcome.status === "error") {
      const globalToast = toastForError(outcome.error);
      if (globalToast) toast(globalToast);
    }
    void queryClient.invalidateQueries({ queryKey: ["history"] });
  };

  const missing =
    stream.error?.code === "missing_variables" && Array.isArray(stream.error.details?.missing)
      ? stream.error.details.missing.filter((name): name is string => typeof name === "string" && !values[name])
      : [];

  return (
    <>
      <PageHeader
        title="Compare"
        description="Run several prompt variants against several models side by side."
        actions={
          stream.isStreaming ? (
            <Button variant="danger" icon={<Square aria-hidden="true" className="size-4" />} onClick={stream.stop}>
              Stop
            </Button>
          ) : (
            <Button
              variant="primary"
              icon={<Play aria-hidden="true" className="size-4" />}
              disabled={!canRun}
              onClick={() => void run()}
            >
              Run comparison
            </Button>
          )
        }
      />

      <div className="space-y-6">
        <Card
          title="Variants"
          description={`Up to ${limits.max_compare_variants} prompt variants.`}
          actions={
            <Button
              size="sm"
              icon={<Plus aria-hidden="true" className="size-4" />}
              disabled={variants.length >= limits.max_compare_variants}
              onClick={() => setVariants((current) => [...current, withKey({ label: "", system: "", prompt: "" })])}
            >
              Add variant
            </Button>
          }
        >
          <div className="grid gap-4 md:grid-cols-2">
            {variants.map((variant, index) => {
              const name = variant.label.trim() || defaultLabel(index);
              return (
                <fieldset key={variant.key} className="min-w-0 space-y-3 rounded-lg border border-line p-3">
                  <legend className="px-1 text-sm font-semibold">{name}</legend>
                  <div className="flex items-end gap-2">
                    <TextField
                      label="Label"
                      className="flex-1"
                      value={variant.label}
                      maxLength={60}
                      placeholder={defaultLabel(index)}
                      onChange={(event) => updateVariant(variant.key, { label: event.target.value })}
                    />
                    <IconButton
                      label={`Duplicate ${name}`}
                      variant="secondary"
                      icon={<Copy aria-hidden="true" className="size-4" />}
                      disabled={variants.length >= limits.max_compare_variants}
                      onClick={() =>
                        setVariants((current) => {
                          const next = [...current];
                          next.splice(index + 1, 0, withKey({ label: variant.label, system: variant.system, prompt: variant.prompt }));
                          return next;
                        })
                      }
                    />
                    <IconButton
                      label={`Remove ${name}`}
                      variant="secondary"
                      icon={<Trash2 aria-hidden="true" className="size-4" />}
                      disabled={variants.length <= 1}
                      onClick={() => setVariants((current) => current.filter((item) => item.key !== variant.key))}
                    />
                  </div>
                  <TextArea
                    label="System prompt"
                    mono
                    rows={2}
                    autoGrow
                    maxHeight={240}
                    value={variant.system}
                    onChange={(event) => updateVariant(variant.key, { system: event.target.value })}
                  />
                  <TextArea
                    label="User prompt"
                    mono
                    rows={4}
                    autoGrow
                    maxHeight={320}
                    value={variant.prompt}
                    error={submitted && !variant.prompt ? "Enter a user prompt." : null}
                    onChange={(event) => updateVariant(variant.key, { prompt: event.target.value })}
                  />
                </fieldset>
              );
            })}
          </div>
        </Card>

        <div className="grid gap-6 lg:grid-cols-2">
          <Card title="Shared variables" description="Every variant receives the same values.">
            <VariablesForm
              variables={variables}
              values={values}
              missing={missing}
              onChange={(name, value) => setValues((current) => ({ ...current, [name]: value }))}
            />
          </Card>
          <Card title="Models and parameters">
            <div className="space-y-5">
              <ModelMultiSelect
                models={catalog.models}
                value={selected}
                max={limits.max_compare_models}
                onChange={setSelected}
              />
              <RunParamsForm
                value={params}
                onChange={setParams}
                supportsTemperature={caps.supportsTemperature}
                supportsThinking={caps.supportsThinking}
                thinkingAlwaysOn={caps.thinkingAlwaysOn}
                maxOutputTokens={caps.maxOutputTokens}
                defaultMaxTokens={Math.min(limits.default_max_tokens, caps.maxOutputTokens)}
                temperatureNote={
                  caps.supportsTemperature && selectedModels.some((model) => !model.supports_temperature)
                    ? "Ignored by models that do not support it."
                    : undefined
                }
              />
            </div>
          </Card>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <p className={cn("text-sm font-medium", overCap ? "text-danger" : "text-fg")} aria-live="polite">
            {variants.length} x {selected.length} = {cellCount} / {limits.max_compare_cells} cells
            {overCap ? " (too many cells: remove a variant or a model)" : ""}
          </p>
          {selected.length === 0 ? <p className="text-sm text-fg-muted">Select at least one model.</p> : null}
        </div>

        {stream.error ? <ErrorState error={stream.error} title="The comparison could not run" /> : null}
        <p role="status" className="sr-only">
          {stream.phase === "streaming" && snapshot
            ? `Comparison running: ${snapshot.labels.length * snapshot.models.length} cells.`
            : stream.phase === "done" && stream.result
              ? `Comparison finished: ${stream.result.summary.ok_count} succeeded, ${stream.result.summary.error_count} failed.`
              : stream.phase === "stopped"
                ? "Comparison stopped."
                : ""}
        </p>

        {/* A request rejected before the stream started (validation) has no grid to show. */}
        {snapshot && !(stream.phase === "error" && stream.start === null) ? (
          <CompareGrid
            snapshot={snapshot}
            cells={stream.cells}
            phase={stream.phase}
            fastest={stream.result?.summary.fastest_cell ?? null}
            cheapest={stream.result?.summary.cheapest_cell ?? null}
            modelLabel={(id) => findModel(catalog.models, id)?.display_name ?? id}
          />
        ) : null}

        {stream.result ? (
          <p className="text-sm text-fg-muted">
            {stream.result.summary.ok_count} succeeded, {stream.result.summary.error_count} failed.{" "}
            <Link
              to={`/history?group_id=${stream.result.id}`}
              className="text-accent-text underline underline-offset-2"
            >
              View in history
            </Link>
          </p>
        ) : null}
      </div>
    </>
  );
}

interface CompareGridProps {
  snapshot: RunSnapshot;
  cells: Record<number, CompareCell>;
  phase: ReturnType<typeof useCompareStream>["phase"];
  fastest: number | null;
  cheapest: number | null;
  modelLabel: (id: string) => string;
}

/** Results grid: rows = variants, columns = models; scrolls horizontally inside its own container. */
function CompareGrid({ snapshot, cells, phase, fastest, cheapest, modelLabel }: CompareGridProps) {
  return (
    <section aria-label="Comparison results" className="min-w-0 rounded-lg border border-line bg-surface">
      <h2 className="border-b border-line px-4 py-3 text-base font-semibold">Results</h2>
      <HorizontalScroll>
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-surface-muted">
              <th scope="col" className="sticky left-0 z-10 w-36 min-w-36 bg-surface-muted px-3 py-2 text-left font-medium">
                Variant
              </th>
              {snapshot.models.map((model) => (
                <th key={model} scope="col" className="min-w-72 px-3 py-2 text-left font-medium">
                  {modelLabel(model)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {snapshot.labels.map((label, variantIndex) => (
              <tr key={`${label}-${variantIndex}`} className="border-t border-line align-top">
                <th scope="row" className="sticky left-0 z-10 bg-surface px-3 py-3 text-left font-medium">
                  {label}
                </th>
                {snapshot.models.map((model, modelIndex) => {
                  const index = variantIndex * snapshot.models.length + modelIndex;
                  return (
                    <td key={model} className="px-3 py-3">
                      <CellView
                        cell={cells[index]}
                        phase={phase}
                        fastest={fastest === index}
                        cheapest={cheapest === index}
                        label={`${label}, ${modelLabel(model)}`}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </HorizontalScroll>
    </section>
  );
}

function CellError({ error }: { error: ErrorBody | null }) {
  return (
    <div role="alert" className="rounded-md border border-danger/40 bg-danger-soft px-3 py-2 text-sm">
      <p className="font-medium text-danger">Error</p>
      <p className="break-words text-fg">{error?.message ?? "The cell failed."}</p>
      {error?.code ? <p className="mt-1 font-mono text-xs text-fg-muted">{error.code}</p> : null}
    </div>
  );
}

function CellView({
  cell,
  phase,
  fastest,
  cheapest,
  label,
}: {
  cell: CompareCell | undefined;
  phase: CompareGridProps["phase"];
  fastest: boolean;
  cheapest: boolean;
  label: string;
}) {
  const [expanded, setExpanded] = useState(false);
  if (!cell) {
    if (phase === "streaming") {
      return (
        <div role="status" className="space-y-2">
          <span className="sr-only">Waiting for {label}</span>
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      );
    }
    return <p className="text-sm text-fg-muted">{phase === "stopped" ? "Stopped before this cell finished." : "No result."}</p>;
  }
  if (cell.status === "error" || !cell.result) return <CellError error={cell.error} />;
  const result = cell.result;
  const long = result.text.length > 400 || result.text.split("\n").length > 8;
  return (
    <div className="space-y-2">
      {fastest || cheapest ? (
        <div className="flex flex-wrap gap-1">
          {fastest ? (
            <Badge tone="success" icon={<Gauge aria-hidden="true" className="size-3.5" />}>
              Fastest
            </Badge>
          ) : null}
          {cheapest ? (
            <Badge tone="info" icon={<Wallet aria-hidden="true" className="size-3.5" />}>
              Cheapest
            </Badge>
          ) : null}
        </div>
      ) : null}
      <div className={cn("relative", long && !expanded && "max-h-56 overflow-hidden")}>
        {result.text ? <Markdown>{result.text}</Markdown> : <p className="text-sm text-fg-muted">Empty response.</p>}
        {long && !expanded ? (
          <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-linear-to-t from-surface" />
        ) : null}
      </div>
      {long ? (
        <Button size="sm" variant="ghost" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
          {expanded ? "Collapse" : "Expand"}
        </Button>
      ) : null}
      <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-fg-muted">
        <div className="flex gap-1">
          <dt>Latency</dt>
          <dd className="font-medium text-fg">{formatLatency(result.latency_ms)}</dd>
        </div>
        <div className="flex gap-1">
          <dt>Tokens</dt>
          <dd className="font-medium text-fg">
            {formatTokens(result.input_tokens)} → {formatTokens(result.output_tokens)}
          </dd>
        </div>
        <div className="flex gap-1">
          <dt>Cost</dt>
          <dd className="font-medium text-fg">{formatCost(result.cost_usd)}</dd>
        </div>
      </dl>
      {result.finish_reason !== "stop" ? <FinishReasonBadge reason={result.finish_reason} /> : null}
    </div>
  );
}
