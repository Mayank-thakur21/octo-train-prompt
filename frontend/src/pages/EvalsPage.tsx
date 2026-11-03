import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { FlaskConical } from "lucide-react";
import { Link } from "react-router";
import { listEvals, listSuites, type EvalListParams } from "../api/endpoints";
import { queryKeys } from "../api/queryKeys";
import type { EvalStatus } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { PassRateBar } from "../components/PassRateBar";
import { StatusBadge } from "../components/StatusBadge";
import { ButtonLink } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { HorizontalScroll } from "../components/ui/HorizontalScroll";
import { Pagination } from "../components/ui/Pagination";
import { Select } from "../components/ui/Select";
import { LoadingBlock } from "../components/ui/Skeleton";
import { useModels } from "../hooks/queries";
import { parseOffset, useUrlFilters } from "../hooks/useUrlFilters";
import { cn } from "../lib/cn";
import { formatDateTime, formatRelativeTime } from "../lib/format";
import { modelName } from "../lib/models";

const PAGE_SIZE = 20;
const STATUSES: EvalStatus[] = ["queued", "running", "completed", "failed", "cancelled"];

const FILTER_DEFAULTS = { status: "", suite_id: "", offset: "0" };

/** Evaluation runs with status and suite filters (kept in the URL, so Back restores them). */
export default function EvalsPage() {
  const models = useModels();
  const [filters, setFilters] = useUrlFilters(FILTER_DEFAULTS);
  const status: EvalStatus | "" = (STATUSES as readonly string[]).includes(filters.status)
    ? (filters.status as EvalStatus)
    : "";
  const suiteId = filters.suite_id;
  const offset = parseOffset(filters.offset);
  const setOffset = (next: number) => setFilters({ offset: String(next) });
  const params: EvalListParams = {
    limit: PAGE_SIZE,
    offset,
    ...(status ? { status } : {}),
    ...(suiteId ? { suite_id: suiteId } : {}),
  };
  const evals = useQuery({
    queryKey: queryKeys.evals(params),
    queryFn: ({ signal }) => listEvals(params, signal),
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      query.state.data?.items.some((item) => item.status === "queued" || item.status === "running") ? 3000 : false,
  });
  const suites = useQuery({
    queryKey: queryKeys.suites({ limit: 100, offset: 0 }),
    queryFn: ({ signal }) => listSuites({ limit: 100, offset: 0 }, signal),
  });

  return (
    <>
      <PageHeader title="Evaluations" description="Results of test suite runs, newest first." />
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:max-w-2xl">
          <Select
            label="Status"
            value={status}
            onChange={(event) => setFilters({ status: event.target.value, offset: "0" })}
          >
            <option value="">All statuses</option>
            {STATUSES.map((item) => (
              <option key={item} value={item}>
                {item.charAt(0).toUpperCase() + item.slice(1)}
              </option>
            ))}
          </Select>
          <Select
            label="Suite"
            value={suiteId}
            onChange={(event) => setFilters({ suite_id: event.target.value, offset: "0" })}
          >
            <option value="">All suites</option>
            {(suites.data?.items ?? []).map((suite) => (
              <option key={suite.id} value={suite.id}>
                {suite.name}
              </option>
            ))}
          </Select>
        </div>

        {evals.isPending ? (
          <LoadingBlock label="Loading evaluations…" lines={6} />
        ) : evals.isError ? (
          <ErrorState error={evals.error} onRetry={() => void evals.refetch()} />
        ) : evals.data.items.length === 0 ? (
          <EmptyState
            icon={<FlaskConical aria-hidden="true" className="size-8" />}
            title={status || suiteId ? "No evaluations match these filters" : "No evaluations yet"}
            description="Open a test suite and use Run evaluation."
            action={
              <ButtonLink to="/suites" variant="primary">
                Go to test suites
              </ButtonLink>
            }
          />
        ) : (
          <>
            <HorizontalScroll className={cn("rounded-lg border border-line bg-surface", evals.isPlaceholderData && "opacity-70")}>
              <table className="w-full min-w-[48rem] text-sm">
                <caption className="sr-only">Evaluation runs</caption>
                <thead className="bg-surface-muted text-left text-xs text-fg-muted">
                  <tr>
                    <th scope="col" className="px-4 py-2 font-medium">Created</th>
                    <th scope="col" className="px-4 py-2 font-medium">Suite</th>
                    <th scope="col" className="px-4 py-2 font-medium">Prompt</th>
                    <th scope="col" className="px-4 py-2 font-medium">Models</th>
                    <th scope="col" className="px-4 py-2 font-medium">Status</th>
                    <th scope="col" className="px-4 py-2 font-medium">Pass rate</th>
                    <th scope="col" className="px-4 py-2 font-medium">Progress</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {evals.data.items.map((run) => (
                    <tr key={run.id} className="hover:bg-surface-muted/60">
                      <td className="px-4 py-2 whitespace-nowrap">
                        <Link to={`/evals/${run.id}`} className="font-medium text-accent-text underline-offset-2 hover:underline" title={formatDateTime(run.created_at)}>
                          {formatRelativeTime(run.created_at)}
                        </Link>
                      </td>
                      <td className="px-4 py-2">{run.suite_name}</td>
                      <td className="px-4 py-2">{run.prompt_label}</td>
                      <td className="px-4 py-2 text-fg-muted">
                        {run.models.map((id) => modelName(models.data?.models, id)).join(", ")}
                      </td>
                      <td className="px-4 py-2">
                        <StatusBadge status={run.status} />
                      </td>
                      <td className="px-4 py-2">
                        <PassRateBar rate={run.pass_rate} />
                      </td>
                      <td className="px-4 py-2 text-fg-muted tabular-nums">
                        {run.progress.completed}/{run.progress.total}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </HorizontalScroll>
            <Pagination label="Evaluation pages" total={evals.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
          </>
        )}
      </div>
    </>
  );
}
