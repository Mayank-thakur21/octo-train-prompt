import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Library, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { createPrompt, getTags, listPrompts, type ArchivedFilter, type PromptListParams, type PromptSort, type SortOrder } from "../api/endpoints";
import { queryKeys } from "../api/queryKeys";
import { PageHeader } from "../components/PageHeader";
import { SavePromptDialog, type SavePromptValues } from "../components/SavePromptDialog";
import { Badge } from "../components/ui/Badge";
import { Button, ButtonLink } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { Pagination } from "../components/ui/Pagination";
import { Select } from "../components/ui/Select";
import { LoadingBlock } from "../components/ui/Skeleton";
import { TextField } from "../components/ui/TextField";
import { useToast } from "../context/toast";
import { useMeta } from "../hooks/queries";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { parseOffset, useUrlFilters } from "../hooks/useUrlFilters";
import { cn } from "../lib/cn";
import { formatDateTime, formatRelativeTime } from "../lib/format";

const PAGE_SIZE = 20;

const SORTS: Array<{ value: string; label: string; sort: PromptSort; order: SortOrder }> = [
  { value: "updated_at:desc", label: "Recently updated", sort: "updated_at", order: "desc" },
  { value: "created_at:desc", label: "Newest", sort: "created_at", order: "desc" },
  { value: "created_at:asc", label: "Oldest", sort: "created_at", order: "asc" },
  { value: "name:asc", label: "Name (A to Z)", sort: "name", order: "asc" },
  { value: "name:desc", label: "Name (Z to A)", sort: "name", order: "desc" },
];

const ARCHIVED_FILTERS: readonly ArchivedFilter[] = ["false", "true", "all"];
const FILTER_DEFAULTS: { q: string; tag: string[]; archived: string; sort: string; offset: string } = {
  q: "",
  tag: [],
  archived: "false",
  sort: SORTS[0]?.value ?? "updated_at:desc",
  offset: "0",
};

/**
 * Prompt library: search, tag filter, archived filter, sort, pagination and "New prompt".
 * The view state lives in the URL, so Back from a prompt restores it.
 */
export default function LibraryPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { toast } = useToast();
  const meta = useMeta();
  const [filters, setFilters] = useUrlFilters(FILTER_DEFAULTS);
  const tags = filters.tag;
  const archived: ArchivedFilter = (ARCHIVED_FILTERS as readonly string[]).includes(filters.archived)
    ? (filters.archived as ArchivedFilter)
    : "false";
  const sortValue = SORTS.some((item) => item.value === filters.sort) ? filters.sort : FILTER_DEFAULTS.sort;
  const offset = parseOffset(filters.offset);
  const setOffset = (next: number) => setFilters({ offset: String(next) });
  // The field keeps its own state so typing never waits for a navigation; the URL follows.
  const [search, setSearch] = useState(filters.q);
  const [creating, setCreating] = useState(false);
  const q = useDebouncedValue(search.trim(), 300);

  const sort = SORTS.find((item) => item.value === sortValue) ?? SORTS[0];
  const params: PromptListParams = {
    q,
    tag: tags,
    archived,
    sort: sort?.sort ?? "updated_at",
    order: sort?.order ?? "desc",
    limit: PAGE_SIZE,
    offset,
  };
  const prompts = useQuery({
    queryKey: queryKeys.prompts(params),
    queryFn: ({ signal }) => listPrompts(params, signal),
    placeholderData: keepPreviousData,
  });
  const tagCounts = useQuery({ queryKey: queryKeys.tags(), queryFn: ({ signal }) => getTags(signal) });

  const createMutation = useMutation({
    mutationFn: (form: SavePromptValues) =>
      createPrompt({
        name: form.name,
        description: form.description,
        tags: form.tags,
        system: form.system || null,
        prompt: form.prompt,
        notes: form.notes,
      }),
    onSuccess: (detail) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.prompts() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tags() });
      toast({ tone: "success", title: `Created "${detail.name}"` });
      setCreating(false);
      void navigate(`/library/${detail.id}`);
    },
  });

  const toggleTag = (tag: string) =>
    setFilters({ tag: tags.includes(tag) ? tags.filter((item) => item !== tag) : [...tags, tag], offset: "0" });
  const filtered = q !== "" || tags.length > 0 || archived !== "false";

  return (
    <>
      <PageHeader
        title="Library"
        description="Versioned prompts you can reopen in the Playground, compare and evaluate."
        actions={
          <Button variant="primary" icon={<Plus aria-hidden="true" className="size-4" />} onClick={() => setCreating(true)}>
            New prompt
          </Button>
        }
      />

      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
          <TextField
            label="Search prompts"
            type="search"
            value={search}
            placeholder="Name, description or prompt text"
            onChange={(event) => {
              setSearch(event.target.value);
              setFilters({ q: event.target.value, offset: "0" });
            }}
          />
          <Select
            label="Show"
            value={archived}
            onChange={(event) => setFilters({ archived: event.target.value, offset: "0" })}
          >
            <option value="false">Active</option>
            <option value="true">Archived</option>
            <option value="all">All</option>
          </Select>
          <Select
            label="Sort by"
            value={sortValue}
            onChange={(event) => setFilters({ sort: event.target.value, offset: "0" })}
          >
            {SORTS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </Select>
        </div>

        {tagCounts.data && tagCounts.data.tags.length > 0 ? (
          <div role="group" aria-label="Filter by tag" className="flex flex-wrap gap-2">
            {tagCounts.data.tags.map((item) => {
              const active = tags.includes(item.tag);
              return (
                <button
                  key={item.tag}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggleTag(item.tag)}
                  className={cn(
                    "rounded-full border px-3 py-1 text-xs font-medium",
                    active
                      ? "border-accent bg-accent text-accent-fg"
                      : "border-line-strong bg-surface text-fg-muted hover:text-fg",
                  )}
                >
                  {item.tag} <span className="opacity-80">({item.count})</span>
                </button>
              );
            })}
          </div>
        ) : null}

        {prompts.isPending ? (
          <LoadingBlock label="Loading prompts…" lines={6} />
        ) : prompts.isError ? (
          <ErrorState error={prompts.error} onRetry={() => void prompts.refetch()} />
        ) : prompts.data.items.length === 0 ? (
          filtered ? (
            <EmptyState
              icon={<Library aria-hidden="true" className="size-8" />}
              title="No prompts match these filters"
              description="Clear the search or tag filters to see every prompt."
              action={
                <Button
                  onClick={() => {
                    setSearch("");
                    setFilters({ q: "", tag: [], archived: "false", offset: "0" });
                  }}
                >
                  Clear filters
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon={<Library aria-hidden="true" className="size-8" />}
              title="Your library is empty"
              description="Save a prompt from the Playground, or create one here."
              action={
                <>
                  <ButtonLink to="/playground" variant="primary">
                    Open the Playground
                  </ButtonLink>
                  <Button onClick={() => setCreating(true)}>New prompt</Button>
                </>
              }
            />
          )
        ) : (
          <>
            <ul aria-label="Prompts" className={cn("divide-y divide-line rounded-lg border border-line bg-surface", prompts.isPlaceholderData && "opacity-70")}>
              {prompts.data.items.map((item) => (
                <li key={item.id} className="px-4 py-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0 flex-1 [overflow-wrap:anywhere]">
                      <Link to={`/library/${item.id}`} className="font-medium text-accent-text underline-offset-2 hover:underline">
                        {item.name}
                      </Link>
                      {item.archived ? (
                        <Badge className="ml-2" tone="neutral">
                          Archived
                        </Badge>
                      ) : null}
                      {item.description ? <p className="mt-0.5 line-clamp-2 text-sm text-fg-muted">{item.description}</p> : null}
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1 text-xs text-fg-muted">
                      <span>
                        {item.version_count} {item.version_count === 1 ? "version" : "versions"}
                      </span>
                      <span title={formatDateTime(item.updated_at)}>Updated {formatRelativeTime(item.updated_at)}</span>
                    </div>
                  </div>
                  {item.tags.length > 0 ? (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {item.tags.map((tag) => (
                        <Badge key={tag} tone="accent">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
            <Pagination
              label="Prompt pages"
              total={prompts.data.total}
              limit={PAGE_SIZE}
              offset={offset}
              onChange={setOffset}
            />
          </>
        )}
      </div>

      {creating ? (
        <SavePromptDialog
          mode="create"
          withContent
          pending={createMutation.isPending}
          error={createMutation.error}
          maxTags={meta.data?.limits.max_tags_per_prompt ?? 10}
          onSubmit={(form) => createMutation.mutate(form)}
          onClose={() => {
            createMutation.reset();
            setCreating(false);
          }}
        />
      ) : null}
    </>
  );
}
