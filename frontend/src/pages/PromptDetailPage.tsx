import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, ChevronLeft, Pencil, Play, RotateCcw, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError } from "../api/client";
import { deletePrompt, diffVersions, getPrompt, getVersion, listVersions, restoreVersion, updatePrompt } from "../api/endpoints";
import { queryKeys } from "../api/queryKeys";
import type { PromptDetail, PromptSettings, PromptUpdate, VersionDetail } from "../api/types";
import { DiffView } from "../components/DiffView";
import { PageHeader } from "../components/PageHeader";
import { Badge } from "../components/ui/Badge";
import { Button, ButtonLink } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { ErrorState } from "../components/ui/ErrorState";
import { Pagination } from "../components/ui/Pagination";
import { ScrollableText } from "../components/ui/ScrollableText";
import { Select } from "../components/ui/Select";
import { LoadingBlock, PageSkeleton } from "../components/ui/Skeleton";
import { Tabs } from "../components/ui/Tabs";
import { TextArea } from "../components/ui/TextArea";
import { TextField } from "../components/ui/TextField";
import { useToast } from "../context/toast";
import { useModels } from "../hooks/queries";
import { cn } from "../lib/cn";
import { formatDateTime, formatRelativeTime } from "../lib/format";
import { modelName } from "../lib/models";
import { parseTags } from "../lib/tags";

const VERSIONS_PAGE = 20;

/** Prompt detail route: loads the prompt, then renders the editor/versions view. */
export default function PromptDetailPage() {
  const { promptId = "" } = useParams();
  const prompt = useQuery({ queryKey: queryKeys.prompt(promptId), queryFn: ({ signal }) => getPrompt(promptId, signal) });

  if (prompt.isPending) {
    return (
      <>
        <PageHeader title="Prompt" eyebrow={<BackLink />} />
        <PageSkeleton />
      </>
    );
  }
  if (prompt.isError) {
    const notFound = prompt.error instanceof ApiError && prompt.error.status === 404;
    return (
      <>
        <PageHeader title={notFound ? "Prompt not found" : "Prompt"} eyebrow={<BackLink />} />
        <ErrorState error={prompt.error} onRetry={notFound ? undefined : () => void prompt.refetch()} />
      </>
    );
  }
  return <PromptDetailView key={promptId} prompt={prompt.data} />;
}

function BackLink() {
  return (
    <Link to="/library" className="inline-flex items-center gap-1 text-accent-text underline-offset-2 hover:underline">
      <ChevronLeft aria-hidden="true" className="size-4" />
      Library
    </Link>
  );
}

function SettingsList({ settings, models }: { settings: PromptSettings; models: Parameters<typeof modelName>[0] }) {
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
      <div>
        <dt className="text-xs text-fg-muted">Model</dt>
        <dd className="font-medium">{settings.model ? modelName(models, settings.model) : "Default"}</dd>
      </div>
      <div>
        <dt className="text-xs text-fg-muted">Temperature</dt>
        <dd className="font-medium">{settings.temperature ?? "Model default"}</dd>
      </div>
      <div>
        <dt className="text-xs text-fg-muted">Max tokens</dt>
        <dd className="font-medium">{settings.max_tokens ?? "Default"}</dd>
      </div>
      <div>
        <dt className="text-xs text-fg-muted">Show thinking</dt>
        <dd className="font-medium">{settings.thinking ? "On" : "Off"}</dd>
      </div>
    </dl>
  );
}

function TemplateBlock({ label, text }: { label: string; text: string | null }) {
  return (
    <div>
      <h4 className="mb-1 text-xs font-semibold tracking-wide text-fg-muted uppercase">{label}</h4>
      {text ? (
        <ScrollableText label={label} text={text} className="max-h-80" />
      ) : (
        <p className="text-sm text-fg-muted">None</p>
      )}
    </div>
  );
}

function PromptDetailView({ prompt }: { prompt: PromptDetail }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { toast } = useToast();
  const models = useModels();
  const latest = prompt.latest_version.version;

  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(prompt.name);
  const [description, setDescription] = useState(prompt.description);
  const [tagsText, setTagsText] = useState(prompt.tags.join(", "));
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [versionsOffset, setVersionsOffset] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [fromVersion, setFromVersion] = useState(Math.max(1, latest - 1));
  const [toVersion, setToVersion] = useState(latest);

  const selectedVersion = selected ?? latest;
  const versions = useQuery({
    queryKey: queryKeys.versions(prompt.id, { limit: VERSIONS_PAGE, offset: versionsOffset }),
    queryFn: ({ signal }) => listVersions(prompt.id, { limit: VERSIONS_PAGE, offset: versionsOffset }, signal),
    placeholderData: keepPreviousData,
  });
  const version = useQuery({
    queryKey: queryKeys.version(prompt.id, selectedVersion),
    queryFn: ({ signal }) => getVersion(prompt.id, selectedVersion, signal),
    initialData: selectedVersion === latest ? prompt.latest_version : undefined,
  });
  const diff = useQuery({
    queryKey: queryKeys.diff(prompt.id, fromVersion, toVersion),
    queryFn: ({ signal }) => diffVersions(prompt.id, fromVersion, toVersion, signal),
  });

  const invalidatePrompt = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.prompt(prompt.id) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.versions(prompt.id) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.prompts() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.tags() }),
    ]);
  };

  const update = useMutation({
    mutationFn: (body: PromptUpdate) => updatePrompt(prompt.id, body),
    onSuccess: async (updated, body) => {
      queryClient.setQueryData(queryKeys.prompt(prompt.id), updated);
      await invalidatePrompt();
      if (body.archived !== undefined) {
        toast({ tone: "success", title: body.archived ? "Prompt archived" : "Prompt restored from the archive" });
      } else {
        toast({ tone: "success", title: "Details saved" });
        setEditing(false);
      }
    },
  });

  const remove = useMutation({
    mutationFn: () => deletePrompt(prompt.id),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: queryKeys.prompt(prompt.id) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.prompts() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tags() });
      toast({ tone: "success", title: `Deleted "${prompt.name}"` });
      void navigate("/library");
    },
  });

  const restore = useMutation({
    mutationFn: (versionNumber: number) => restoreVersion(prompt.id, versionNumber),
    onSuccess: async (created: VersionDetail, restoredFrom) => {
      await invalidatePrompt();
      setSelected(created.version);
      setFromVersion(restoredFrom);
      setToVersion(created.version);
      toast({ tone: "success", title: `Restored v${restoredFrom} as v${created.version}` });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "no_changes") {
        toast({ tone: "info", title: "That version is identical to the latest version." });
      } else if (error instanceof ApiError && error.status !== 401 && error.status !== 429 && error.status !== 0) {
        toast({ tone: "error", title: "Restore failed", description: error.message });
      }
    },
  });

  const saveDetails = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    update.mutate({ name: name.trim(), description: description.trim(), tags: parseTags(tagsText) });
  };

  const versionOptions = Array.from({ length: latest }, (_, index) => latest - index);
  const catalog = models.data?.models;

  return (
    <>
      <PageHeader
        title={prompt.name}
        documentTitle={`${prompt.name} (Library)`}
        eyebrow={<BackLink />}
        description={prompt.description || undefined}
        actions={
          <>
            <ButtonLink
              to={`/playground?prompt=${prompt.id}&version=${latest}`}
              variant="primary"
              icon={<Play aria-hidden="true" className="size-4" />}
            >
              Open in Playground
            </ButtonLink>
            <Button
              icon={
                prompt.archived ? <ArchiveRestore aria-hidden="true" className="size-4" /> : <Archive aria-hidden="true" className="size-4" />
              }
              loading={update.isPending && update.variables.archived !== undefined}
              onClick={() => update.mutate({ archived: !prompt.archived })}
            >
              {prompt.archived ? "Unarchive" : "Archive"}
            </Button>
            <Button variant="danger" icon={<Trash2 aria-hidden="true" className="size-4" />} onClick={() => setConfirmDelete(true)}>
              Delete
            </Button>
          </>
        }
      />

      <div className="space-y-6">
        <Card
          title="Details"
          actions={
            !editing ? (
              <Button size="sm" icon={<Pencil aria-hidden="true" className="size-4" />} onClick={() => setEditing(true)}>
                Edit details
              </Button>
            ) : undefined
          }
        >
          {editing ? (
            <form className="space-y-4" onSubmit={saveDetails} noValidate>
              <TextField
                label="Name"
                value={name}
                maxLength={120}
                required
                error={!name.trim() ? "Enter a name." : null}
                onChange={(event) => setName(event.target.value)}
              />
              <TextArea
                label="Description"
                value={description}
                rows={2}
                maxLength={2000}
                onChange={(event) => setDescription(event.target.value)}
              />
              <TextField
                label="Tags"
                value={tagsText}
                hint="Comma separated"
                onChange={(event) => setTagsText(event.target.value)}
              />
              {update.error && update.variables?.archived === undefined ? <ErrorState error={update.error} compact /> : null}
              <div className="flex gap-2">
                <Button type="submit" variant="primary" loading={update.isPending}>
                  Save details
                </Button>
                <Button
                  onClick={() => {
                    setEditing(false);
                    setName(prompt.name);
                    setDescription(prompt.description);
                    setTagsText(prompt.tags.join(", "));
                    update.reset();
                  }}
                >
                  Cancel
                </Button>
              </div>
            </form>
          ) : (
            <dl className="grid gap-3 text-sm sm:grid-cols-3">
              <div>
                <dt className="text-xs text-fg-muted">Tags</dt>
                <dd className="mt-1 flex flex-wrap gap-1">
                  {prompt.tags.length > 0 ? prompt.tags.map((tag) => <Badge key={tag} tone="accent">{tag}</Badge>) : "None"}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-fg-muted">Status</dt>
                <dd className="mt-1">{prompt.archived ? <Badge>Archived</Badge> : <Badge tone="success">Active</Badge>}</dd>
              </div>
              <div>
                <dt className="text-xs text-fg-muted">Updated</dt>
                <dd className="mt-1" title={formatDateTime(prompt.updated_at)}>
                  {formatRelativeTime(prompt.updated_at)}
                </dd>
              </div>
            </dl>
          )}
        </Card>

        <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
          <Card title="Versions" description={`${prompt.version_count} in total, newest first.`} bodyClassName="p-2">
            {versions.isPending ? (
              <LoadingBlock label="Loading versions…" />
            ) : versions.isError ? (
              <ErrorState error={versions.error} onRetry={() => void versions.refetch()} compact />
            ) : (
              <>
                <ul className="space-y-1">
                  {versions.data.items.map((item) => {
                    const active = item.version === selectedVersion;
                    return (
                      <li key={item.id}>
                        <button
                          type="button"
                          aria-pressed={active}
                          onClick={() => setSelected(item.version)}
                          className={cn(
                            "w-full rounded-md px-3 py-2 text-left text-sm",
                            active ? "bg-accent-soft text-accent-text" : "hover:bg-surface-muted",
                          )}
                        >
                          <span className="flex items-center justify-between gap-2">
                            <span className="font-medium">v{item.version}</span>
                            <span className="text-xs text-fg-muted" title={formatDateTime(item.created_at)}>
                              {formatRelativeTime(item.created_at)}
                            </span>
                          </span>
                          {item.notes ? <span className="mt-0.5 block truncate text-xs text-fg-muted">{item.notes}</span> : null}
                        </button>
                      </li>
                    );
                  })}
                </ul>
                <Pagination
                  label="Version pages"
                  total={versions.data.total}
                  limit={VERSIONS_PAGE}
                  offset={versionsOffset}
                  onChange={setVersionsOffset}
                />
              </>
            )}
          </Card>

          <Card
            title={`Version ${selectedVersion}`}
            description={selectedVersion === latest ? "Latest version" : undefined}
            actions={
              <>
                <ButtonLink
                  size="sm"
                  to={`/playground?prompt=${prompt.id}&version=${selectedVersion}`}
                  icon={<Play aria-hidden="true" className="size-4" />}
                >
                  Open in Playground
                </ButtonLink>
                <Button
                  size="sm"
                  icon={<RotateCcw aria-hidden="true" className="size-4" />}
                  disabled={selectedVersion === latest}
                  loading={restore.isPending}
                  onClick={() => restore.mutate(selectedVersion)}
                >
                  Restore
                </Button>
              </>
            }
          >
            {version.isPending ? (
              <LoadingBlock label="Loading version…" />
            ) : version.isError ? (
              <ErrorState error={version.error} onRetry={() => void version.refetch()} compact />
            ) : (
              <div className="space-y-4">
                <TemplateBlock label="System prompt" text={version.data.system} />
                <TemplateBlock label="User prompt" text={version.data.prompt} />
                <SettingsList settings={version.data.settings} models={catalog} />
                <p className="text-sm [overflow-wrap:anywhere]">
                  <span className="text-fg-muted">Notes: </span>
                  {version.data.notes || "None"}
                </p>
                {version.data.variables.length > 0 ? (
                  <p className="flex min-w-0 flex-wrap items-center gap-1 text-sm">
                    <span className="text-fg-muted">Variables:</span>
                    {version.data.variables.map((variable) => (
                      <Badge key={variable.name} tone="accent">
                        {variable.name}
                        {variable.default !== null ? ` = ${variable.default}` : ""}
                      </Badge>
                    ))}
                  </p>
                ) : null}
              </div>
            )}
          </Card>
        </div>

        <Card title="Compare versions">
          <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:max-w-xl">
            <Select label="From version" value={String(fromVersion)} onChange={(event) => setFromVersion(Number(event.target.value))}>
              {versionOptions.map((number) => (
                <option key={number} value={number}>
                  v{number}
                </option>
              ))}
            </Select>
            <Select label="To version" value={String(toVersion)} onChange={(event) => setToVersion(Number(event.target.value))}>
              {versionOptions.map((number) => (
                <option key={number} value={number}>
                  v{number}
                </option>
              ))}
            </Select>
          </div>
          {diff.isPending ? (
            <LoadingBlock label="Loading diff…" />
          ) : diff.isError ? (
            <ErrorState error={diff.error} onRetry={() => void diff.refetch()} compact />
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2">
                {diff.data.settings_changed ? <Badge tone="warning">Settings changed</Badge> : <Badge>Settings unchanged</Badge>}
                {!diff.data.system.changed && !diff.data.prompt.changed ? <Badge>Templates identical</Badge> : null}
              </div>
              <Tabs
                label="Diff view"
                items={[
                  {
                    id: "side",
                    label: "Side by side",
                    content: (
                      <div className="space-y-4">
                        <DiffView title="System prompt" diff={diff.data.system} fromLabel={`v${diff.data.from_version}`} toLabel={`v${diff.data.to_version}`} />
                        <DiffView title="User prompt" diff={diff.data.prompt} fromLabel={`v${diff.data.from_version}`} toLabel={`v${diff.data.to_version}`} />
                        {diff.data.settings_changed ? (
                          <div className="grid gap-3 rounded-lg border border-line p-3 md:grid-cols-2">
                            <div>
                              <h4 className="mb-1 text-xs font-semibold text-fg-muted">Settings v{diff.data.from_version}</h4>
                              <SettingsList settings={diff.data.settings_from} models={catalog} />
                            </div>
                            <div>
                              <h4 className="mb-1 text-xs font-semibold text-fg-muted">Settings v{diff.data.to_version}</h4>
                              <SettingsList settings={diff.data.settings_to} models={catalog} />
                            </div>
                          </div>
                        ) : null}
                      </div>
                    ),
                  },
                  {
                    id: "unified",
                    label: "Unified",
                    content: (
                      <div className="space-y-3">
                        {[
                          { title: "System prompt", text: diff.data.system.unified },
                          { title: "User prompt", text: diff.data.prompt.unified },
                        ].map((block) => (
                          <div key={block.title}>
                            <h4 className="mb-1 text-sm font-semibold">{block.title}</h4>
                            <ScrollableText label={`${block.title} unified diff`} text={block.text || "No differences."} />
                          </div>
                        ))}
                      </div>
                    ),
                  },
                ]}
              />
            </div>
          )}
        </Card>
      </div>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete this prompt?"
        message={`"${prompt.name}" and all ${prompt.version_count} versions will be deleted. History entries keep their copies.`}
        confirmLabel="Delete prompt"
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
