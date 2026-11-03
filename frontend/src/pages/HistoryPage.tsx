import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, Trash2, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { clearHistory, listHistory, type HistoryListParams } from "../api/endpoints";
import { queryKeys } from "../api/queryKeys";
import type { HistorySource, HistoryStatus, ProviderId } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { Badge } from "../components/ui/Badge";
import { Button, ButtonLink } from "../components/ui/Button";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { HorizontalScroll } from "../components/ui/HorizontalScroll";
import { Pagination } from "../components/ui/Pagination";
import { Select } from "../components/ui/Select";
import { LoadingBlock } from "../components/ui/Skeleton";
import { TextField } from "../components/ui/TextField";
import { useToast } from "../context/toast";
import { useModels } from "../hooks/queries";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { parseOffset, useUrlFilters } from "../hooks/useUrlFilters";
import { cn } from "../lib/cn";
import { formatCost, formatDateTime, formatLatency, formatRelativeTime, formatTokens, PROVIDER_LABELS } from "../lib/format";
import { groupModels, modelName } from "../lib/models";

const PAGE_SIZE = 20;
const FILTER_DEFAULTS = { q: "", model: "", provider: "", status: "", source: "", group_id: "", offset: "0" };
const PROVIDERS: readonly ProviderId[] = ["anthropic", "openai", "gemini", "demo"];
const STATUSES: readonly HistoryStatus[] = ["success", "error", "cancelled"];
const SOURCES: readonly HistorySource[] = ["run", "compare"];

/** `value` when it is one of `allowed`, else "" (unknown URL values are ignored). */
function oneOf<T extends string>(value: string, allowed: readonly T[]): T | "" {
  return (allowed as readonly string[]).includes(value) ? (value as T) : "";
}

/**
 * Run history with search, model/provider/status/source filters and "Clear history".
 * Filters, search and page live in the URL, so Back from an entry restores the list.
 */
export default function HistoryPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const models = useModels();
  const [filters, setFilters] = useUrlFilters(FILTER_DEFAULTS);
  const groupId = filters.group_id;
  const model = filters.model;
  const provider = oneOf(filters.provider, PROVIDERS);
  const status = oneOf(filters.status, STATUSES);
  const source = oneOf(filters.source, SOURCES);
  const offset = parseOffset(filters.offset);
  // The field keeps its own state so typing never waits for a navigation; the URL follows.
  const [search, setSearch] = useState(filters.q);
  const [confirmClear, setConfirmClear] = useState(false);
  const q = useDebouncedValue(search.trim(), 300);
  const setOffset = (next: number) => setFilters({ offset: String(next) });

  const params: HistoryListParams = {
    limit: PAGE_SIZE,
    offset,
    ...(q ? { q } : {}),
    ...(model ? { model } : {}),
    ...(provider ? { provider } : {}),
    ...(status ? { status } : {}),
    ...(source ? { source } : {}),
    ...(groupId ? { group_id: groupId } : {}),
  };
  const history = useQuery({
    queryKey: queryKeys.history(params),
    queryFn: ({ signal }) => listHistory(params, signal),
    placeholderData: keepPreviousData,
  });

  const clear = useMutation({
    mutationFn: clearHistory,
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.history() });
      toast({ tone: "success", title: `Deleted ${result.deleted} history ${result.deleted === 1 ? "entry" : "entries"}` });
      setConfirmClear(false);
      setOffset(0);
    },
  });
  const filtered = Boolean(q || model || provider || status || source || groupId);
  const catalog = models.data?.models;

  return (
    <>
      <PageHeader
        title="History"
        description="Every run and comparison cell, newest first."
        actions={
          <Button variant="danger" icon={<Trash2 aria-hidden="true" className="size-4" />} onClick={() => setConfirmClear(true)}>
            Clear history
          </Button>
        }
      />
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <TextField
            label="Search history"
            type="search"
            className="sm:col-span-2 lg:col-span-1"
            value={search}
            placeholder="Prompt or output text"
            onChange={(event) => {
              setSearch(event.target.value);
              setFilters({ q: event.target.value, offset: "0" });
            }}
          />
          <Select
            label="Model"
            value={model}
            onChange={(event) => setFilters({ model: event.target.value, offset: "0" })}
          >
            <option value="">All models</option>
            {groupModels(catalog ?? []).map((group) => (
              <optgroup key={group.provider} label={group.label}>
                {group.models.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.display_name}
                  </option>
                ))}
              </optgroup>
            ))}
          </Select>
          <Select
            label="Provider"
            value={provider}
            onChange={(event) => setFilters({ provider: event.target.value, offset: "0" })}
          >
            <option value="">All providers</option>
            {PROVIDERS.map((id) => (
              <option key={id} value={id}>
                {PROVIDER_LABELS[id]}
              </option>
            ))}
          </Select>
          <Select
            label="Status"
            value={status}
            onChange={(event) => setFilters({ status: event.target.value, offset: "0" })}
          >
            <option value="">All statuses</option>
            <option value="success">Success</option>
            <option value="error">Error</option>
            <option value="cancelled">Cancelled</option>
          </Select>
          <Select
            label="Source"
            value={source}
            onChange={(event) => setFilters({ source: event.target.value, offset: "0" })}
          >
            <option value="">All sources</option>
            <option value="run">Playground runs</option>
            <option value="compare">Comparisons</option>
          </Select>
        </div>

        {groupId ? (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Badge tone="accent">Comparison {groupId.slice(0, 8)}</Badge>
            <Button
              size="sm"
              variant="ghost"
              icon={<X aria-hidden="true" className="size-4" />}
              onClick={() => setFilters({ group_id: "", offset: "0" })}
            >
              Show all history
            </Button>
          </div>
        ) : null}

        {history.isPending ? (
          <LoadingBlock label="Loading history…" lines={6} />
        ) : history.isError ? (
          <ErrorState error={history.error} onRetry={() => void history.refetch()} />
        ) : history.data.items.length === 0 ? (
          <EmptyState
            icon={<History aria-hidden="true" className="size-8" />}
            title={filtered ? "No history matches these filters" : "No runs yet"}
            description={filtered ? "Change or clear the filters." : "Runs from the Playground and Compare appear here."}
            action={
              !filtered ? (
                <ButtonLink to="/playground" variant="primary">
                  Open the Playground
                </ButtonLink>
              ) : undefined
            }
          />
        ) : (
          <>
            <HorizontalScroll className={cn("rounded-lg border border-line bg-surface", history.isPlaceholderData && "opacity-70")}>
              <table className="w-full min-w-[52rem] text-sm">
                <caption className="sr-only">Run history</caption>
                <thead className="bg-surface-muted text-left text-xs text-fg-muted">
                  <tr>
                    <th scope="col" className="px-4 py-2 font-medium">Time</th>
                    <th scope="col" className="px-4 py-2 font-medium">Model</th>
                    <th scope="col" className="px-4 py-2 font-medium">Status</th>
                    <th scope="col" className="px-4 py-2 font-medium">Prompt</th>
                    <th scope="col" className="px-4 py-2 text-right font-medium">Tokens</th>
                    <th scope="col" className="px-4 py-2 text-right font-medium">Latency</th>
                    <th scope="col" className="px-4 py-2 text-right font-medium">Cost</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {history.data.items.map((item) => (
                    <tr key={item.id} className="hover:bg-surface-muted/60">
                      <td className="px-4 py-2 whitespace-nowrap">
                        <Link
                          to={`/history/${item.id}`}
                          title={formatDateTime(item.created_at)}
                          className="font-medium text-accent-text underline-offset-2 hover:underline"
                        >
                          {formatRelativeTime(item.created_at)}
                        </Link>
                        {item.source === "compare" ? <span className="ml-2 text-xs text-fg-muted">compare</span> : null}
                      </td>
                      <td className="px-4 py-2">{modelName(catalog, item.model)}</td>
                      <td className="px-4 py-2">
                        <StatusBadge status={item.status} />
                      </td>
                      <td className="max-w-80 px-4 py-2">
                        <span className="line-clamp-2 break-words text-fg-muted">{item.prompt_preview}</span>
                      </td>
                      <td className="px-4 py-2 text-right whitespace-nowrap tabular-nums">
                        {formatTokens(item.input_tokens)} → {formatTokens(item.output_tokens)}
                      </td>
                      <td className="px-4 py-2 text-right whitespace-nowrap">{formatLatency(item.latency_ms)}</td>
                      <td className="px-4 py-2 text-right whitespace-nowrap">{formatCost(item.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </HorizontalScroll>
            <Pagination label="History pages" total={history.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
          </>
        )}
      </div>

      <ConfirmDialog
        open={confirmClear}
        title="Clear all history?"
        message="Every saved run and comparison cell will be deleted. This cannot be undone."
        confirmLabel="Clear history"
        danger
        pending={clear.isPending}
        error={clear.error ? <ErrorState error={clear.error} compact /> : undefined}
        onConfirm={() => clear.mutate()}
        onCancel={() => {
          clear.reset();
          setConfirmClear(false);
        }}
      />
    </>
  );
}
