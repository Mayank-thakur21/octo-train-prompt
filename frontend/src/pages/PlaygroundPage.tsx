import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, LayoutTemplate, Play, Save, Square } from "lucide-react";
import { useEffect, useEffectEvent, useId, useMemo, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router";
import { ApiError } from "../api/client";
import { createPrompt, createVersion, getHistoryItem, getPrompt, getVersion } from "../api/endpoints";
import { queryKeys } from "../api/queryKeys";
import type { BuiltinTemplate, ID, Limits, ModelsResponse, RunRequest } from "../api/types";
import { OutputPanel } from "../components/OutputPanel";
import { PageHeader } from "../components/PageHeader";
import { RunMetrics } from "../components/RunMetrics";
import { RunParamsForm } from "../components/RunParamsForm";
import { SavePromptDialog, type SavePromptValues } from "../components/SavePromptDialog";
import { TemplatePickerDialog } from "../components/TemplatePickerDialog";
import { TokenEstimate } from "../components/TokenEstimate";
import { VariablesForm } from "../components/VariablesForm";
import { ModelPicker } from "../components/ModelPicker";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ErrorState } from "../components/ui/ErrorState";
import { PageSkeleton } from "../components/ui/Skeleton";
import { TextArea } from "../components/ui/TextArea";
import { toastForError, useToast } from "../context/toast";
import { useMeta, useModels, useTemplates } from "../hooks/queries";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { useHotkey } from "../hooks/useHotkey";
import { usePersistedDraft } from "../hooks/usePersistedDraft";
import { useRunStream } from "../hooks/useRunStream";
import { useTokenEstimate } from "../hooks/useTokenEstimate";
import { formatNumber } from "../lib/format";
import { defaultMaxTokens, findModel } from "../lib/models";
import { isRunParamsValue, paramsAreValid, type RunParamsValue } from "../lib/params";
import { isRecord, isStringRecord, readStorage, STORAGE_KEYS, writeStorage } from "../lib/storage";
import { extractVariables, nonEmptyValues, renderTemplate } from "../lib/template";

/** Library version the editor was loaded from (enables "Save new version"). */
interface LinkedPrompt {
  promptId: ID;
  name: string;
  version: number;
  versionId: ID;
  /** Template texts of that version, to detect unchanged content for `prompt_version_id`. */
  system: string;
  prompt: string;
}

interface PlaygroundDraft {
  system: string;
  prompt: string;
  values: Record<string, string>;
  model: string | null;
  params: RunParamsValue;
  linked: LinkedPrompt | null;
}

const EMPTY_DRAFT: PlaygroundDraft = {
  system: "",
  prompt: "",
  values: {},
  model: null,
  params: { temperature: null, maxTokens: null, thinking: false },
  linked: null,
};

function isLinkedPrompt(value: unknown): value is LinkedPrompt {
  return (
    isRecord(value) &&
    typeof value.promptId === "string" &&
    typeof value.name === "string" &&
    typeof value.version === "number" &&
    typeof value.versionId === "string" &&
    typeof value.system === "string" &&
    typeof value.prompt === "string"
  );
}

function isPlaygroundDraft(value: unknown): value is PlaygroundDraft {
  return (
    isRecord(value) &&
    typeof value.system === "string" &&
    typeof value.prompt === "string" &&
    isStringRecord(value.values) &&
    (value.model === null || typeof value.model === "string") &&
    isRunParamsValue(value.params) &&
    (value.linked === null || isLinkedPrompt(value.linked))
  );
}

/** Where the editor content comes from, derived from the query string. */
type Source =
  | { kind: "draft" }
  | { kind: "history"; id: string }
  | { kind: "prompt"; id: string; version: number | null }
  | { kind: "template"; id: string };

function sourceFromParams(params: URLSearchParams): Source {
  const history = params.get("history");
  if (history) return { kind: "history", id: history };
  const prompt = params.get("prompt");
  if (prompt) {
    const version = Number.parseInt(params.get("version") ?? "", 10);
    return { kind: "prompt", id: prompt, version: Number.isInteger(version) && version > 0 ? version : null };
  }
  const template = params.get("template");
  if (template) return { kind: "template", id: template };
  return { kind: "draft" };
}

/** Loads the data for a non-draft source and converts it into the editor's initial state. */
function useSourceInitial(source: Source): { initial: PlaygroundDraft | null; error: unknown; retry: () => void } {
  const history = useQuery({
    queryKey: queryKeys.historyItem(source.kind === "history" ? source.id : ""),
    queryFn: ({ signal }) => getHistoryItem(source.kind === "history" ? source.id : "", signal),
    enabled: source.kind === "history",
  });
  const prompt = useQuery({
    queryKey: queryKeys.prompt(source.kind === "prompt" ? source.id : ""),
    queryFn: ({ signal }) => getPrompt(source.kind === "prompt" ? source.id : "", signal),
    enabled: source.kind === "prompt",
  });
  const versionNumber = source.kind === "prompt" ? source.version : null;
  const version = useQuery({
    queryKey: queryKeys.version(source.kind === "prompt" ? source.id : "", versionNumber ?? 0),
    queryFn: ({ signal }) => getVersion(source.kind === "prompt" ? source.id : "", versionNumber ?? 1, signal),
    enabled: source.kind === "prompt" && versionNumber !== null,
  });
  const templates = useTemplates(source.kind === "template");

  switch (source.kind) {
    case "draft":
      return { initial: null, error: null, retry: () => undefined };
    case "history": {
      const item = history.data;
      return {
        initial: item
          ? {
              system: item.system_template ?? "",
              prompt: item.prompt_template,
              values: item.variables,
              model: item.model,
              params: {
                temperature: item.params.temperature,
                maxTokens: item.params.max_tokens,
                thinking: item.params.thinking,
              },
              linked: null,
            }
          : null,
        error: history.error,
        retry: () => void history.refetch(),
      };
    }
    case "prompt": {
      const detail = prompt.data;
      const selected = versionNumber === null ? detail?.latest_version : version.data;
      return {
        initial:
          detail && selected
            ? {
                system: selected.system ?? "",
                prompt: selected.prompt,
                values: {},
                model: selected.settings.model,
                params: {
                  temperature: selected.settings.temperature,
                  maxTokens: selected.settings.max_tokens,
                  thinking: selected.settings.thinking,
                },
                linked: {
                  promptId: detail.id,
                  name: detail.name,
                  version: selected.version,
                  versionId: selected.id,
                  system: selected.system ?? "",
                  prompt: selected.prompt,
                },
              }
            : null,
        error: prompt.error ?? version.error,
        retry: () => {
          void prompt.refetch();
          if (versionNumber !== null) void version.refetch();
        },
      };
    }
    case "template": {
      const template = templates.data?.templates.find((item) => item.id === source.id);
      const missing = templates.isSuccess && !template;
      return {
        initial: template
          ? { ...EMPTY_DRAFT, system: template.system ?? "", prompt: template.prompt }
          : null,
        error: missing ? new ApiError(404, "not_found", `Template "${source.id}" does not exist.`) : templates.error,
        retry: () => void templates.refetch(),
      };
    }
  }
}

/** Query parameters that ask the Playground to load something once. */
const SOURCE_PARAMS = ["prompt", "version", "template", "history", "autorun"] as const;

/**
 * Playground route. A `?prompt=`, `?template=` or `?history=` link is a one-time
 * instruction: once its content has loaded it becomes the saved draft and the
 * parameters are removed from the URL. The editor always starts from the
 * draft, so edits survive reloads, Back and the sidebar link.
 */
export default function PlaygroundPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const source = sourceFromParams(searchParams);
  const autorunRequested = searchParams.get("autorun") === "1" && source.kind === "history";
  // `autorun=1` survives the URL clean-up as navigation state until the run starts.
  const autorun = isRecord(location.state) && location.state.autorun === true;
  const meta = useMeta();
  const models = useModels();
  const loaded = useSourceInitial(source);
  const loadedInitial = loaded.initial;

  useEffect(() => {
    if (source.kind === "draft" || !loadedInitial) return;
    writeStorage(STORAGE_KEYS.playgroundDraft, loadedInitial);
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        for (const name of SOURCE_PARAMS) next.delete(name);
        return next;
      },
      { replace: true, state: autorunRequested ? { autorun: true } : null },
    );
  }, [source.kind, loadedInitial, autorunRequested, setSearchParams]);

  const error = meta.error ?? models.error ?? loaded.error;
  if (error) {
    return (
      <>
        <PageHeader title="Playground" />
        <ErrorState
          error={error}
          onRetry={() => {
            void meta.refetch();
            void models.refetch();
            loaded.retry();
          }}
        />
      </>
    );
  }
  // While a source loads (and for the render in which it becomes the draft) the
  // editor stays unmounted, so it then mounts with the new draft.
  if (!meta.data || !models.data || source.kind !== "draft") {
    return (
      <>
        <PageHeader title="Playground" />
        <PageSkeleton />
      </>
    );
  }

  return (
    <PlaygroundEditor
      initial={readStorage(STORAGE_KEYS.playgroundDraft, EMPTY_DRAFT, isPlaygroundDraft)}
      catalog={models.data}
      limits={meta.data.limits}
      autorun={autorun}
      onAutorunConsumed={() => setSearchParams((current) => current, { replace: true, state: null })}
    />
  );
}

interface PlaygroundEditorProps {
  initial: PlaygroundDraft;
  catalog: ModelsResponse;
  limits: Limits;
  autorun: boolean;
  onAutorunConsumed: () => void;
}

function PlaygroundEditor({ initial, catalog, limits, autorun, onAutorunConsumed }: PlaygroundEditorProps) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const stream = useRunStream();

  const initialModel = (() => {
    const wanted = findModel(catalog.models, initial.model);
    return wanted?.available ? wanted.id : catalog.default_model;
  })();
  const [system, setSystem] = useState(initial.system);
  const [prompt, setPrompt] = useState(initial.prompt);
  const [values, setValues] = useState<Record<string, string>>(initial.values);
  const [model, setModel] = useState(initialModel);
  const [params, setParams] = useState<RunParamsValue>(() => {
    const spec = findModel(catalog.models, initialModel);
    const max = spec?.max_output_tokens ?? limits.max_output_tokens;
    const wanted = initial.params.maxTokens ?? defaultMaxTokens(limits, spec);
    return { ...initial.params, maxTokens: Math.min(Math.max(1, wanted), max) };
  });
  const [linked, setLinked] = useState<LinkedPrompt | null>(initial.linked);
  const [dialog, setDialog] = useState<"templates" | "create" | "version" | null>(null);
  const [promptError, setPromptError] = useState<string | null>(null);
  const maxTokensId = useId();

  const spec = findModel(catalog.models, model);
  const maxOutput = spec?.max_output_tokens ?? limits.max_output_tokens;
  const supportsTemperature = spec?.supports_temperature ?? false;
  const supportsThinking = spec?.supports_thinking ?? false;

  // Variables follow the templates with a short debounce.
  const debouncedSystem = useDebouncedValue(system, 200);
  const debouncedPrompt = useDebouncedValue(prompt, 200);
  const variables = useMemo(() => extractVariables(debouncedSystem, debouncedPrompt), [debouncedSystem, debouncedPrompt]);
  const variableNames = useMemo(() => extractVariables(system, prompt).map((item) => item.name), [system, prompt]);
  const sentValues = nonEmptyValues(values, variableNames);
  const preview = useMemo(
    () => renderTemplate(debouncedSystem, debouncedPrompt, nonEmptyValues(values, variables.map((item) => item.name))),
    [debouncedSystem, debouncedPrompt, values, variables],
  );

  const estimate = useTokenEstimate(prompt ? { model, system: system || null, prompt, variables: sentValues } : null);

  // Persist the draft so a reload, Back or another page restores the editor.
  const draft = useMemo<PlaygroundDraft>(
    () => ({ system, prompt, values, model, params, linked }),
    [system, prompt, values, model, params, linked],
  );
  usePersistedDraft(STORAGE_KEYS.playgroundDraft, draft);

  const unchangedFromLinked = linked !== null && linked.system === system && linked.prompt === prompt;
  const settingsForSave = {
    model,
    temperature: supportsTemperature ? params.temperature : null,
    max_tokens: params.maxTokens,
    thinking: supportsThinking && params.thinking,
  };

  const runNow = async () => {
    if (stream.isStreaming) return;
    if (!prompt) {
      setPromptError("Enter a user prompt to run.");
      return;
    }
    setPromptError(null);
    if (!paramsAreValid(params, maxOutput)) {
      // The field shows why; focusing it makes screen readers announce the error.
      document.getElementById(maxTokensId)?.focus();
      return;
    }
    const req: RunRequest = {
      model,
      system: system || null,
      prompt,
      variables: sentValues,
      temperature: settingsForSave.temperature,
      max_tokens: params.maxTokens,
      thinking: settingsForSave.thinking,
      prompt_version_id: unchangedFromLinked ? linked.versionId : null,
    };
    const outcome = await stream.run(req);
    if (outcome.status === "error") {
      const globalToast = toastForError(outcome.error);
      if (globalToast) toast(globalToast);
    }
    void queryClient.invalidateQueries({ queryKey: queryKeys.history() });
  };

  // Ctrl/Cmd+Enter runs from anywhere on the page, except while a dialog is open.
  useHotkey({ key: "Enter", mod: true, enabled: dialog === null }, () => void runNow());

  const startAutorun = useEffectEvent(() => {
    onAutorunConsumed();
    void runNow();
  });
  // `autorun=1` starts the run once after mount. The start is deferred to a task so a
  // development StrictMode remount (which aborts in-flight streams) cancels the timer
  // instead of the stream; removing the query parameter prevents a second run.
  useEffect(() => {
    if (!autorun) return undefined;
    const timer = window.setTimeout(() => startAutorun(), 0);
    return () => window.clearTimeout(timer);
  }, [autorun]);

  const createMutation = useMutation({
    mutationFn: (form: SavePromptValues) =>
      createPrompt({
        name: form.name,
        description: form.description,
        tags: form.tags,
        system: system || null,
        prompt,
        notes: form.notes,
        settings: settingsForSave,
      }),
    onSuccess: (detail) => {
      setLinked({
        promptId: detail.id,
        name: detail.name,
        version: detail.latest_version.version,
        versionId: detail.latest_version.id,
        system: detail.latest_version.system ?? "",
        prompt: detail.latest_version.prompt,
      });
      setDialog(null);
      toast({
        tone: "success",
        title: `Saved "${detail.name}" to the library`,
        action: { label: "Open in Library", to: `/library/${detail.id}` },
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.prompts() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tags() });
    },
  });

  const versionMutation = useMutation({
    mutationFn: (form: SavePromptValues) => {
      if (!linked) throw new ApiError(0, "internal_error", "No library prompt is loaded.");
      return createVersion(linked.promptId, { system: system || null, prompt, notes: form.notes, settings: settingsForSave });
    },
    onSuccess: (version) => {
      if (!linked) return;
      setLinked({ ...linked, version: version.version, versionId: version.id, system: version.system ?? "", prompt: version.prompt });
      setDialog(null);
      toast({
        tone: "success",
        title: `Saved version ${version.version} of "${linked.name}"`,
        action: { label: "Open in Library", to: `/library/${linked.promptId}` },
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.prompt(linked.promptId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.versions(linked.promptId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.prompts() });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "no_changes") {
        setDialog(null);
        toast({ tone: "info", title: "No changes since the latest version." });
      }
    },
  });

  const changeModel = (id: string) => {
    setModel(id);
    const next = findModel(catalog.models, id);
    if (next && params.maxTokens !== null && params.maxTokens > next.max_output_tokens) {
      setParams({ ...params, maxTokens: next.max_output_tokens });
    }
  };

  const pickTemplate = (template: BuiltinTemplate) => {
    setSystem(template.system ?? "");
    setPrompt(template.prompt);
    setLinked(null);
    setDialog(null);
    toast({ tone: "info", title: `Loaded the "${template.name}" template` });
  };

  const missing =
    stream.error?.code === "missing_variables" && Array.isArray(stream.error.details?.missing)
      ? stream.error.details.missing.filter((name): name is string => typeof name === "string" && !sentValues[name])
      : [];
  const warnings = stream.result?.warnings ?? stream.start?.warnings ?? [];
  const modelLabel = (id: string) => findModel(catalog.models, id)?.display_name ?? id;

  return (
    <>
      <PageHeader
        title="Playground"
        description="Write a prompt, fill its variables and stream the answer from any configured model."
        eyebrow={
          linked ? (
            <span className="flex max-w-full min-w-0 flex-wrap items-center gap-2">
              <BookOpen aria-hidden="true" className="size-4 shrink-0" />
              <Link
                to={`/library/${linked.promptId}`}
                className="min-w-0 font-medium text-accent-text underline underline-offset-2 [overflow-wrap:anywhere]"
              >
                {linked.name}
              </Link>
              <Badge tone="accent">v{linked.version}</Badge>
              {!unchangedFromLinked ? <Badge tone="warning">edited</Badge> : null}
            </span>
          ) : undefined
        }
        actions={
          <>
            <Button icon={<LayoutTemplate aria-hidden="true" className="size-4" />} onClick={() => setDialog("templates")}>
              Templates
            </Button>
            <Button icon={<Save aria-hidden="true" className="size-4" />} disabled={!prompt} onClick={() => setDialog("create")}>
              Save as prompt
            </Button>
            {linked ? (
              <Button icon={<Save aria-hidden="true" className="size-4" />} disabled={!prompt} onClick={() => setDialog("version")}>
                Save new version
              </Button>
            ) : null}
          </>
        }
      />

      <div className="grid min-w-0 gap-6 lg:grid-cols-2">
        <div className="min-w-0 space-y-6">
          <Card title="Prompt">
            <div className="space-y-4">
              <TextArea
                label="System prompt"
                value={system}
                mono
                rows={3}
                autoGrow
                maxHeight={360}
                placeholder="Optional instructions, e.g. You are a concise assistant."
                onChange={(event) => setSystem(event.target.value)}
              />
              <TextArea
                label="User prompt"
                value={prompt}
                mono
                rows={8}
                autoGrow
                required
                error={promptError}
                placeholder="Write your prompt. Use {{variable}} or {{variable|default}} placeholders."
                onChange={(event) => {
                  setPrompt(event.target.value);
                  if (promptError) setPromptError(null);
                }}
              />
              <TokenEstimate estimate={estimate.estimate} pending={estimate.isPending} error={estimate.error} />
            </div>
          </Card>

          <Card title="Variables" description="Empty fields are not sent, so defaults apply.">
            <VariablesForm
              variables={variables}
              values={values}
              missing={missing}
              onChange={(name, value) => setValues((current) => ({ ...current, [name]: value }))}
            />
            {variables.length > 0 ? (
              <details className="mt-4 rounded-md border border-line">
                <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-fg-muted">Rendered preview</summary>
                <div className="space-y-2 border-t border-line px-3 py-2">
                  {preview.system ? (
                    <pre className="font-mono text-xs whitespace-pre-wrap text-fg-muted">{preview.system}</pre>
                  ) : null}
                  <pre className="font-mono text-xs whitespace-pre-wrap text-fg">{preview.prompt}</pre>
                  {preview.missing.length > 0 ? (
                    <p className="text-xs text-warning">Missing: {preview.missing.join(", ")}</p>
                  ) : null}
                </div>
              </details>
            ) : null}
          </Card>
        </div>

        <div className="min-w-0 space-y-6">
          <Card title="Parameters">
            <div className="space-y-4">
              <ModelPicker models={catalog.models} value={model} onChange={changeModel} />
              <RunParamsForm
                value={params}
                onChange={setParams}
                supportsTemperature={supportsTemperature}
                supportsThinking={supportsThinking}
                thinkingAlwaysOn={spec?.thinking_always_on ?? false}
                maxOutputTokens={maxOutput}
                defaultMaxTokens={defaultMaxTokens(limits, spec)}
                maxTokensId={maxTokensId}
              />
            </div>
          </Card>

          <div className="flex flex-wrap items-center gap-3">
            {stream.isStreaming ? (
              <Button variant="danger" icon={<Square aria-hidden="true" className="size-4" />} onClick={stream.stop}>
                Stop
              </Button>
            ) : (
              <Button variant="primary" icon={<Play aria-hidden="true" className="size-4" />} onClick={() => void runNow()}>
                Run
              </Button>
            )}
            <p className="text-xs text-fg-muted">
              <kbd className="rounded border border-line px-1 font-mono">Ctrl</kbd> /{" "}
              <kbd className="rounded border border-line px-1 font-mono">Cmd</kbd> +{" "}
              <kbd className="rounded border border-line px-1 font-mono">Enter</kbd> runs from anywhere on the page
            </p>
          </div>

          <OutputPanel
            phase={stream.phase}
            doneMessage={
              stream.result
                ? `Run finished: ${formatNumber(stream.result.output_tokens)} output ${stream.result.output_tokens === 1 ? "token" : "tokens"}.`
                : undefined
            }
            text={stream.text}
            thinking={stream.thinking}
            warnings={warnings}
            error={stream.error}
            footer={stream.result ? <RunMetrics result={stream.result} modelName={modelLabel(stream.result.model)} /> : undefined}
          />
          {stream.result?.id ? (
            <p className="text-xs text-fg-muted">
              Saved to{" "}
              <Link to={`/history/${stream.result.id}`} className="text-accent-text underline underline-offset-2">
                history
              </Link>
              .
            </p>
          ) : null}
        </div>
      </div>

      {dialog === "templates" ? <TemplatePickerDialog onPick={pickTemplate} onClose={() => setDialog(null)} /> : null}
      {dialog === "create" ? (
        <SavePromptDialog
          mode="create"
          pending={createMutation.isPending}
          error={createMutation.error}
          maxTags={limits.max_tags_per_prompt}
          onSubmit={(form) => createMutation.mutate(form)}
          onClose={() => {
            createMutation.reset();
            setDialog(null);
          }}
        />
      ) : null}
      {dialog === "version" && linked ? (
        <SavePromptDialog
          mode="version"
          promptName={linked.name}
          pending={versionMutation.isPending}
          error={versionMutation.error instanceof ApiError && versionMutation.error.code === "no_changes" ? null : versionMutation.error}
          maxTags={limits.max_tags_per_prompt}
          onSubmit={(form) => versionMutation.mutate(form)}
          onClose={() => {
            versionMutation.reset();
            setDialog(null);
          }}
        />
      ) : null}
    </>
  );
}
