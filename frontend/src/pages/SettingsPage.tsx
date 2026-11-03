import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, Eye, EyeOff, KeyRound, PlugZap, Upload } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { exportData, getModels, importData, type ExportInclude, type ImportConflict } from "../api/endpoints";
import type { ExportDocument, ImportResult, Meta } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ErrorState } from "../components/ui/ErrorState";
import { IconButton } from "../components/ui/IconButton";
import { Select } from "../components/ui/Select";
import { LoadingBlock } from "../components/ui/Skeleton";
import { inputClasses, LABEL_CLASSES } from "../components/ui/styles";
import { THEME_PREFERENCES, useSettings, type ThemePreference } from "../context/settings";
import { useToast } from "../context/toast";
import { useMeta, useModels } from "../hooks/queries";
import { formatBytes, formatNumber } from "../lib/format";
import { modelName } from "../lib/models";
import { isRecord } from "../lib/storage";

const THEME_LABELS: Record<ThemePreference, string> = { dark: "Dark", light: "Light", system: "System" };

function ApiKeyCard({ authRequired }: { authRequired: boolean | undefined }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { apiKey, setApiKey, clearApiKey } = useSettings();
  const inputId = useId();
  const [draft, setDraft] = useState(apiKey);
  const [visible, setVisible] = useState(false);

  const test = useMutation({
    mutationFn: () => getModels(),
    meta: { silent: true },
  });

  const save = (event: FormEvent) => {
    event.preventDefault();
    setApiKey(draft);
    test.reset();
    void queryClient.invalidateQueries();
    toast({ tone: "success", title: draft.trim() ? "API key saved" : "API key cleared" });
  };

  return (
    <Card title="Connection" description="The API key is sent as the X-API-Key header and stored only in this browser.">
      <form className="space-y-4" onSubmit={save}>
        <div className="flex flex-col gap-1.5">
          <label htmlFor={inputId} className={LABEL_CLASSES}>
            API key
          </label>
          <div className="flex gap-2">
            <input
              id={inputId}
              type={visible ? "text" : "password"}
              autoComplete="off"
              spellCheck={false}
              value={draft}
              className={inputClasses(false, "h-10 font-mono")}
              onChange={(event) => setDraft(event.target.value)}
            />
            <IconButton
              label={visible ? "Hide key" : "Show key"}
              variant="secondary"
              aria-pressed={visible}
              icon={visible ? <EyeOff aria-hidden="true" className="size-4" /> : <Eye aria-hidden="true" className="size-4" />}
              onClick={() => setVisible((value) => !value)}
            />
          </div>
          <p className="text-xs text-fg-muted">
            {apiKey ? "A key is saved in this browser." : "No key saved."}{" "}
            {authRequired === true
              ? "This server requires an API key."
              : authRequired === false
                ? "This server does not require an API key."
                : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="submit" variant="primary" icon={<KeyRound aria-hidden="true" className="size-4" />}>
            Save API key
          </Button>
          <Button
            disabled={!apiKey && !draft}
            onClick={() => {
              clearApiKey();
              setDraft("");
              test.reset();
              void queryClient.invalidateQueries();
              toast({ tone: "info", title: "API key cleared" });
            }}
          >
            Clear
          </Button>
          <Button icon={<PlugZap aria-hidden="true" className="size-4" />} loading={test.isPending} onClick={() => test.mutate()}>
            Test connection
          </Button>
        </div>
        <div aria-live="polite">
          {test.isSuccess ? (
            <p role="status" className="rounded-md border border-success/40 bg-success-soft px-3 py-2 text-sm">
              <span className="font-medium text-success">Connected. </span>
              {test.data.models.filter((model) => model.available).length} of {test.data.models.length} models are available.
            </p>
          ) : null}
          {test.isError ? <ErrorState error={test.error} title="Connection failed" compact /> : null}
        </div>
      </form>
    </Card>
  );
}

function ThemeCard() {
  const { theme, setTheme } = useSettings();
  const name = useId();
  return (
    <Card title="Appearance">
      <fieldset>
        <legend className={LABEL_CLASSES}>Theme</legend>
        <div className="mt-2 flex flex-wrap gap-2">
          {THEME_PREFERENCES.map((option) => (
            <label
              key={option}
              className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-line-strong px-3 py-2 text-sm has-[:checked]:border-accent has-[:checked]:bg-accent-soft"
            >
              <input
                type="radio"
                name={name}
                value={option}
                className="size-4 accent-accent"
                checked={theme === option}
                onChange={() => setTheme(option)}
              />
              {THEME_LABELS[option]}
            </label>
          ))}
        </div>
        <p className="mt-2 text-xs text-fg-muted">System follows your operating system setting and updates when it changes.</p>
      </fieldset>
    </Card>
  );
}

function ServerInfoCard({ meta }: { meta: Meta }) {
  const models = useModels();
  const limits = meta.limits;
  const rows: Array<[string, string]> = [
    ["Prompt / system characters", `${formatNumber(limits.max_prompt_chars)} / ${formatNumber(limits.max_system_chars)}`],
    ["Rendered characters", formatNumber(limits.max_rendered_chars)],
    ["Variables (value characters)", `${limits.max_variables} (${formatNumber(limits.max_variable_value_chars)})`],
    ["Max output tokens (default)", `${formatNumber(limits.max_output_tokens)} (${formatNumber(limits.default_max_tokens)})`],
    ["Compare variants x models (cells)", `${limits.max_compare_variants} x ${limits.max_compare_models} (${limits.max_compare_cells})`],
    ["Cases per suite / assertions per case", `${limits.max_cases_per_suite} / ${limits.max_assertions_per_case}`],
    ["Evaluation models (calls)", `${limits.max_eval_models} (${formatNumber(limits.max_eval_calls)})`],
    ["Tags / versions per prompt", `${limits.max_tags_per_prompt} / ${limits.max_versions_per_prompt}`],
    ["Request body / import size", `${formatBytes(limits.max_body_bytes)} / ${formatBytes(limits.import_max_bytes)}`],
    ["Provider timeout", `${limits.request_timeout_seconds} s`],
  ];
  return (
    <Card title="Server">
      <dl className="grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs text-fg-muted">Version</dt>
          <dd className="font-medium">{meta.version}</dd>
        </div>
        <div>
          <dt className="text-xs text-fg-muted">Authentication</dt>
          <dd className="font-medium">{meta.auth_required ? "API key required" : "Open (no key required)"}</dd>
        </div>
        <div>
          <dt className="text-xs text-fg-muted">Default model</dt>
          <dd className="font-medium">{modelName(models.data?.models, meta.default_model)}</dd>
        </div>
        <div>
          <dt className="text-xs text-fg-muted">Mode</dt>
          <dd className="font-medium">{meta.demo_mode ? "Demo mode (offline models only)" : "Live providers"}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-xs text-fg-muted">Providers</dt>
          <dd className="mt-1 flex flex-wrap gap-2">
            {meta.providers.map((provider) => (
              <Badge key={provider.id} tone={provider.configured ? "success" : "neutral"}>
                {provider.display_name}: {provider.configured ? "configured" : "not configured"}
              </Badge>
            ))}
          </dd>
        </div>
      </dl>
      <details className="mt-4 rounded-md border border-line">
        <summary className="cursor-pointer px-3 py-2 text-sm font-medium">Limits</summary>
        <dl className="divide-y divide-line border-t border-line text-sm">
          {rows.map(([label, value]) => (
            <div key={label} className="flex flex-wrap justify-between gap-2 px-3 py-1.5">
              <dt className="text-fg-muted">{label}</dt>
              <dd className="font-medium tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
      </details>
    </Card>
  );
}

/** Triggers a browser download of a Blob. */
function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function ImportSummary({ result }: { result: ImportResult }) {
  const counts = (label: string, value: ImportResult["prompts"]) =>
    `${label}: ${value.created} created, ${value.updated} updated, ${value.skipped} skipped, ${value.renamed} renamed`;
  return (
    <div role="status" className="space-y-1 rounded-md border border-success/40 bg-success-soft px-3 py-2 text-sm">
      <p className="font-medium text-success">Import finished</p>
      <p>{counts("Prompts", result.prompts)}</p>
      <p>{counts("Suites", result.suites)}</p>
      <p>History: {result.history.created} created</p>
      {result.warnings.length > 0 ? (
        <ul className="list-disc pl-5 text-fg-muted">
          {result.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function DataCard({ importMaxBytes }: { importMaxBytes: number }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const fileId = useId();
  const [include, setInclude] = useState<ExportInclude[]>(["prompts", "suites"]);
  const [file, setFile] = useState<File | null>(null);
  const [conflict, setConflict] = useState<ImportConflict>("skip");
  const [legacy, setLegacy] = useState(false);

  const exporter = useMutation({
    mutationFn: () => exportData(include),
    onSuccess: ({ blob, filename }) => {
      downloadBlob(blob, filename);
      toast({ tone: "success", title: `Exported ${filename}` });
    },
  });

  const importer = useMutation({
    mutationFn: async (selected: File): Promise<ImportResult> => {
      if (selected.size > importMaxBytes) {
        throw new Error(`The file is larger than the ${formatBytes(importMaxBytes)} import limit.`);
      }
      let parsed: unknown;
      try {
        parsed = JSON.parse(await selected.text());
      } catch {
        throw new Error("The file is not valid JSON.");
      }
      if (!isRecord(parsed)) throw new Error("The file does not contain an export document.");
      return importData(parsed as unknown as ExportDocument, conflict, legacy);
    },
    onSuccess: () => {
      for (const key of [["prompts"], ["prompt"], ["tags"], ["suites"], ["suite"], ["history"]]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      toast({ tone: "success", title: "Import finished" });
    },
  });

  const toggle = (value: ExportInclude, checked: boolean) =>
    setInclude((current) => (checked ? [...current, value] : current.filter((item) => item !== value)));

  return (
    <Card title="Data" description="Back up or move prompts, suites and history as a JSON document.">
      <div className="grid gap-6 lg:grid-cols-2">
        <section aria-labelledby="export-heading" className="space-y-3">
          <h3 id="export-heading" className="text-sm font-semibold">
            Export
          </h3>
          <fieldset className="flex flex-wrap gap-4">
            <legend className="sr-only">Include in the export</legend>
            {(
              [
                { value: "prompts", label: "Prompts" },
                { value: "suites", label: "Test suites" },
                { value: "history", label: "History" },
              ] as const
            ).map((option) => (
              <label key={option.value} className="inline-flex cursor-pointer items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="size-4 accent-accent"
                  checked={include.includes(option.value)}
                  onChange={(event) => toggle(option.value, event.target.checked)}
                />
                {option.label}
              </label>
            ))}
          </fieldset>
          <Button
            icon={<Download aria-hidden="true" className="size-4" />}
            disabled={include.length === 0}
            loading={exporter.isPending}
            onClick={() => exporter.mutate()}
          >
            Export
          </Button>
          {exporter.error ? <ErrorState error={exporter.error} compact /> : null}
        </section>

        <section aria-labelledby="import-heading" className="space-y-3">
          <h3 id="import-heading" className="text-sm font-semibold">
            Import
          </h3>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={fileId} className={LABEL_CLASSES}>
              Import file
            </label>
            <input
              id={fileId}
              type="file"
              accept="application/json,.json"
              className="text-sm file:mr-3 file:rounded-md file:border file:border-line-strong file:bg-surface file:px-3 file:py-1.5 file:text-sm file:text-fg"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                importer.reset();
              }}
            />
          </div>
          <Select label="When a name already exists" value={conflict} onChange={(event) => setConflict(event.target.value as ImportConflict)}>
            <option value="skip">Skip the imported item</option>
            <option value="rename">Import with a new name</option>
            <option value="overwrite">Overwrite the existing item</option>
          </Select>
          <label className="inline-flex cursor-pointer items-center gap-2 text-sm">
            <input type="checkbox" className="size-4 accent-accent" checked={legacy} onChange={(event) => setLegacy(event.target.checked)} />
            Convert legacy {"{placeholders}"}
          </label>
          <div>
            <Button
              icon={<Upload aria-hidden="true" className="size-4" />}
              disabled={!file}
              loading={importer.isPending}
              onClick={() => {
                if (file) importer.mutate(file);
              }}
            >
              Import
            </Button>
          </div>
          {importer.isSuccess ? <ImportSummary result={importer.data} /> : null}
          {importer.error ? <ErrorState error={importer.error} title="Import failed" compact /> : null}
        </section>
      </div>
    </Card>
  );
}

/** Settings: API key, theme, server information and data import/export. */
export default function SettingsPage() {
  const meta = useMeta();
  return (
    <>
      <PageHeader title="Settings" description="Connection, appearance and data management for this browser." />
      <div className="grid gap-6 lg:grid-cols-2">
        <ApiKeyCard authRequired={meta.data?.auth_required} />
        <ThemeCard />
        {meta.isPending ? (
          <Card title="Server">
            <LoadingBlock label="Loading server information…" />
          </Card>
        ) : meta.isError ? (
          <Card title="Server">
            <ErrorState error={meta.error} onRetry={() => void meta.refetch()} compact />
          </Card>
        ) : (
          <ServerInfoCard meta={meta.data} />
        )}
        <div className="lg:col-span-2">
          <DataCard importMaxBytes={meta.data?.limits.import_max_bytes ?? 5 * 1024 * 1024} />
        </div>
      </div>
    </>
  );
}
