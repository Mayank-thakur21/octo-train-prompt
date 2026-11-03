import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ListChecks, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { createSuite, listSuites, type SuiteListParams } from "../api/endpoints";
import { queryKeys } from "../api/queryKeys";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { Button } from "../components/ui/Button";
import { Dialog } from "../components/ui/Dialog";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { Pagination } from "../components/ui/Pagination";
import { LoadingBlock } from "../components/ui/Skeleton";
import { TextArea } from "../components/ui/TextArea";
import { TextField } from "../components/ui/TextField";
import { useToast } from "../context/toast";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { cn } from "../lib/cn";
import { formatDateTime, formatPercent, formatRelativeTime } from "../lib/format";

const PAGE_SIZE = 20;

function NewSuiteDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const create = useMutation({
    mutationFn: () => createSuite({ name: name.trim(), description: description.trim() }),
    onSuccess: (suite) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.suites() });
      toast({ tone: "success", title: `Created "${suite.name}"` });
      onClose();
      void navigate(`/suites/${suite.id}`);
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (name.trim()) create.mutate();
  };
  return (
    <Dialog
      open
      onClose={onClose}
      closeOnBackdrop={name === "" && description === ""}
      title="New test suite"
      description="A suite groups test cases that are evaluated together."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="new-suite-form" variant="primary" loading={create.isPending}>
            Create suite
          </Button>
        </>
      }
    >
      <form id="new-suite-form" className="space-y-4" noValidate onSubmit={submit}>
        <TextField
          label="Name"
          value={name}
          maxLength={120}
          required
          data-autofocus="true"
          error={submitted && !name.trim() ? "Enter a name." : null}
          onChange={(event) => setName(event.target.value)}
        />
        <TextArea label="Description" value={description} rows={3} maxLength={2000} onChange={(event) => setDescription(event.target.value)} />
        {create.error ? <ErrorState error={create.error} compact /> : null}
      </form>
    </Dialog>
  );
}

/** Test suite list with search, pagination and a "New suite" dialog. */
export default function SuitesPage() {
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const q = useDebouncedValue(search.trim(), 300);
  const params: SuiteListParams = { q, limit: PAGE_SIZE, offset };
  const suites = useQuery({
    queryKey: queryKeys.suites(params),
    queryFn: ({ signal }) => listSuites(params, signal),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader
        title="Test suites"
        description="Cases with variables and assertions that score a prompt across models."
        actions={
          <Button variant="primary" icon={<Plus aria-hidden="true" className="size-4" />} onClick={() => setCreating(true)}>
            New suite
          </Button>
        }
      />
      <div className="space-y-4">
        <TextField
          label="Search suites"
          type="search"
          className="sm:max-w-sm"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setOffset(0);
          }}
        />
        {suites.isPending ? (
          <LoadingBlock label="Loading suites…" lines={5} />
        ) : suites.isError ? (
          <ErrorState error={suites.error} onRetry={() => void suites.refetch()} />
        ) : suites.data.items.length === 0 ? (
          <EmptyState
            icon={<ListChecks aria-hidden="true" className="size-8" />}
            title={q ? "No suites match the search" : "No test suites yet"}
            description={q ? "Try another name." : "Create a suite, add cases with assertions, then run an evaluation."}
            action={!q ? <Button variant="primary" onClick={() => setCreating(true)}>New suite</Button> : undefined}
          />
        ) : (
          <>
            <ul
              aria-label="Test suites"
              className={cn("divide-y divide-line rounded-lg border border-line bg-surface", suites.isPlaceholderData && "opacity-70")}
            >
              {suites.data.items.map((suite) => (
                <li key={suite.id} className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1 [overflow-wrap:anywhere]">
                    <Link to={`/suites/${suite.id}`} className="font-medium text-accent-text underline-offset-2 hover:underline">
                      {suite.name}
                    </Link>
                    {suite.description ? <p className="mt-0.5 line-clamp-2 text-sm text-fg-muted">{suite.description}</p> : null}
                    <p className="mt-1 text-xs text-fg-muted">
                      {suite.case_count} {suite.case_count === 1 ? "case" : "cases"} · updated{" "}
                      <span title={formatDateTime(suite.updated_at)}>{formatRelativeTime(suite.updated_at)}</span>
                    </p>
                  </div>
                  {suite.last_eval ? (
                    <Link to={`/evals/${suite.last_eval.id}`} className="flex items-center gap-2 text-sm">
                      <span className="text-fg-muted">Last run</span>
                      <StatusBadge status={suite.last_eval.status} />
                      <span className="font-medium">{formatPercent(suite.last_eval.pass_rate)}</span>
                    </Link>
                  ) : (
                    <span className="text-xs text-fg-muted">Never evaluated</span>
                  )}
                </li>
              ))}
            </ul>
            <Pagination label="Suite pages" total={suites.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
          </>
        )}
      </div>
      {creating ? <NewSuiteDialog onClose={() => setCreating(false)} /> : null}
    </>
  );
}
