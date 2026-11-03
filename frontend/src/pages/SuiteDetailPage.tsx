import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, FlaskConical, ListChecks, Pencil, Plus, Trash2 } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError } from "../api/client";
import { deleteCase, deleteSuite, getSuite, listPrompts, listVersions, startEval, updateSuite } from "../api/endpoints";
import { queryKeys } from "../api/queryKeys";
import type { EvalCreate, Limits, ModelInfo, ModelsResponse, SuiteDetail, SuiteUpdate, TestCase } from "../api/types";
import { CaseEditorDialog } from "../components/CaseEditorDialog";
import { ModelMultiSelect } from "../components/ModelMultiSelect";
import { ModelPicker } from "../components/ModelPicker";
import { PageHeader } from "../components/PageHeader";
import { RunParamsForm } from "../components/RunParamsForm";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { HorizontalScroll } from "../components/ui/HorizontalScroll";
import { IconButton } from "../components/ui/IconButton";
import { Select } from "../components/ui/Select";
import { PageSkeleton } from "../components/ui/Skeleton";
import { TextArea } from "../components/ui/TextArea";
import { TextField } from "../components/ui/TextField";
import { useToast } from "../context/toast";
import { useMeta, useModels } from "../hooks/queries";
import { summarizeAssertions } from "../lib/assertions";
import { cn } from "../lib/cn";
import { combineCapabilities, findModel } from "../lib/models";
import { paramsAreValid, type RunParamsValue } from "../lib/params";

/** Suite detail route: suite editing, cases and the "Run evaluation" panel. */
export default function SuiteDetailPage() {
  const { suiteId = "" } = useParams();
  const suite = useQuery({ queryKey: queryKeys.suite(suiteId), queryFn: ({ signal }) => getSuite(suiteId, signal) });
  const meta = useMeta();
  const models = useModels();

  if (suite.isError) {
    const notFound = suite.error instanceof ApiError && suite.error.status === 404;
    return (
      <>
        <PageHeader title={notFound ? "Suite not found" : "Test suite"} eyebrow={<BackLink />} />
        <ErrorState error={suite.error} onRetry={notFound ? undefined : () => void suite.refetch()} />
      </>
    );
  }
  if (!suite.data || !meta.data || !models.data) {
    return (
      <>
        <PageHeader title="Test suite" eyebrow={<BackLink />} />
        {meta.error || models.error ? (
          <ErrorState
            error={meta.error ?? models.error}
            onRetry={() => {
              void meta.refetch();
              void models.refetch();
            }}
          />
        ) : (
          <PageSkeleton />
        )}
      </>
    );
  }
  return <SuiteView key={suiteId} suite={suite.data} limits={meta.data.limits} catalog={models.data} />;
}

function BackLink() {
  return (
    <Link to="/suites" className="inline-flex items-center gap-1 text-accent-text underline-offset-2 hover:underline">
      <ChevronLeft aria-hidden="true" className="size-4" />
      Test suites
    </Link>
  );
}

function SuiteView({ suite, limits, catalog }: { suite: SuiteDetail; limits: Limits; catalog: ModelsResponse }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(suite.name);
  const [description, setDescription] = useState(suite.description);
  const [editor, setEditor] = useState<{ testCase?: TestCase } | null>(null);
  const [caseToDelete, setCaseToDelete] = useState<TestCase | null>(null);
  const [confirmDeleteSuite, setConfirmDeleteSuite] = useState(false);

  const update = useMutation({
    mutationFn: (body: SuiteUpdate) => updateSuite(suite.id, body),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.suite(suite.id), updated);
      void queryClient.invalidateQueries({ queryKey: queryKeys.suites() });
      toast({ tone: "success", title: "Suite saved" });
      setEditing(false);
    },
  });
  const removeCase = useMutation({
    mutationFn: (testCase: TestCase) => deleteCase(suite.id, testCase.id),
    onSuccess: (_result, testCase) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.suite(suite.id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.suites() });
      toast({ tone: "success", title: `Deleted "${testCase.name}"` });
      setCaseToDelete(null);
    },
  });
  const removeSuite = useMutation({
    mutationFn: () => deleteSuite(suite.id),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: queryKeys.suite(suite.id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.suites() });
      toast({ tone: "success", title: `Deleted "${suite.name}"` });
      void navigate("/suites");
    },
  });

  const saveDetails = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim()) update.mutate({ name: name.trim(), description: description.trim() });
  };

  const atCaseLimit = suite.cases.length >= limits.max_cases_per_suite;

  return (
    <>
      <PageHeader
        title={suite.name}
        documentTitle={`${suite.name} (Test suite)`}
        eyebrow={<BackLink />}
        description={suite.description || undefined}
        actions={
          <Button variant="danger" icon={<Trash2 aria-hidden="true" className="size-4" />} onClick={() => setConfirmDeleteSuite(true)}>
            Delete suite
          </Button>
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
            <form className="space-y-4" noValidate onSubmit={saveDetails}>
              <TextField
                label="Name"
                value={name}
                maxLength={120}
                required
                error={!name.trim() ? "Enter a name." : null}
                onChange={(event) => setName(event.target.value)}
              />
              <TextArea label="Description" value={description} rows={3} maxLength={2000} onChange={(event) => setDescription(event.target.value)} />
              {update.error ? <ErrorState error={update.error} compact /> : null}
              <div className="flex gap-2">
                <Button type="submit" variant="primary" loading={update.isPending}>
                  Save details
                </Button>
                <Button
                  onClick={() => {
                    setEditing(false);
                    setName(suite.name);
                    setDescription(suite.description);
                    update.reset();
                  }}
                >
                  Cancel
                </Button>
              </div>
            </form>
          ) : (
            <p className="text-sm text-fg-muted [overflow-wrap:anywhere]">{suite.description || "No description."}</p>
          )}
        </Card>

        <Card
          title="Cases"
          description={`${suite.cases.length} of ${limits.max_cases_per_suite} cases.`}
          actions={
            <Button
              size="sm"
              variant="primary"
              icon={<Plus aria-hidden="true" className="size-4" />}
              disabled={atCaseLimit}
              onClick={() => setEditor({})}
            >
              Add case
            </Button>
          }
          bodyClassName="p-0"
        >
          {suite.cases.length === 0 ? (
            <div className="p-4">
              <EmptyState
                icon={<ListChecks aria-hidden="true" className="size-8" />}
                title="No cases yet"
                description="Each case sets variables for the prompt and lists assertions the output must pass."
                action={
                  <Button variant="primary" onClick={() => setEditor({})}>
                    Add case
                  </Button>
                }
              />
            </div>
          ) : (
            <HorizontalScroll>
              <table className="w-full min-w-[32rem] text-sm">
                <thead className="bg-surface-muted text-left text-xs text-fg-muted">
                  <tr>
                    <th scope="col" className="px-4 py-2 font-medium">
                      Name
                    </th>
                    <th scope="col" className="px-4 py-2 font-medium">
                      Variables
                    </th>
                    <th scope="col" className="px-4 py-2 font-medium">
                      Assertions
                    </th>
                    <th scope="col" className="px-4 py-2 text-right font-medium">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {suite.cases.map((testCase) => (
                    <tr key={testCase.id}>
                      <td className="px-4 py-2 font-medium [overflow-wrap:anywhere]">{testCase.name}</td>
                      <td className="px-4 py-2 text-fg-muted">{Object.keys(testCase.variables).length}</td>
                      <td className="px-4 py-2 text-fg-muted [overflow-wrap:anywhere]">
                        {testCase.assertions.length}: {summarizeAssertions(testCase.assertions)}
                      </td>
                      <td className="px-4 py-2">
                        <div className="flex justify-end gap-1">
                          <IconButton
                            label={`Edit ${testCase.name}`}
                            size="sm"
                            icon={<Pencil aria-hidden="true" className="size-4" />}
                            onClick={() => setEditor({ testCase })}
                          />
                          <IconButton
                            label={`Delete ${testCase.name}`}
                            size="sm"
                            icon={<Trash2 aria-hidden="true" className="size-4" />}
                            onClick={() => setCaseToDelete(testCase)}
                          />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </HorizontalScroll>
          )}
        </Card>

        <EvalForm suite={suite} limits={limits} catalog={catalog} />
      </div>

      {editor ? (
        <CaseEditorDialog
          key={editor.testCase?.id ?? "new"}
          suiteId={suite.id}
          testCase={editor.testCase}
          models={catalog.models}
          maxAssertions={limits.max_assertions_per_case}
          onClose={() => setEditor(null)}
        />
      ) : null}
      <ConfirmDialog
        open={caseToDelete !== null}
        title="Delete this case?"
        message={`"${caseToDelete?.name ?? ""}" will be removed from the suite. Past evaluations keep their snapshot.`}
        confirmLabel="Delete case"
        danger
        pending={removeCase.isPending}
        error={removeCase.error ? <ErrorState error={removeCase.error} compact /> : undefined}
        onConfirm={() => {
          if (caseToDelete) removeCase.mutate(caseToDelete);
        }}
        onCancel={() => {
          removeCase.reset();
          setCaseToDelete(null);
        }}
      />
      <ConfirmDialog
        open={confirmDeleteSuite}
        title="Delete this suite?"
        message={`"${suite.name}" and its ${suite.cases.length} cases will be deleted. Evaluation results are kept.`}
        confirmLabel="Delete suite"
        danger
        pending={removeSuite.isPending}
        error={removeSuite.error ? <ErrorState error={removeSuite.error} compact /> : undefined}
        onConfirm={() => removeSuite.mutate()}
        onCancel={() => {
          removeSuite.reset();
          setConfirmDeleteSuite(false);
        }}
      />
    </>
  );
}

type PromptSource = "library" | "adhoc";

/** "Run evaluation" panel: prompt source, models, parameters and judge model. */
function EvalForm({ suite, limits, catalog }: { suite: SuiteDetail; limits: Limits; catalog: ModelsResponse }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const sourceName = useId();
  const [source, setSource] = useState<PromptSource>("library");
  const [promptId, setPromptId] = useState("");
  const [versionId, setVersionId] = useState("");
  const [system, setSystem] = useState("");
  const [prompt, setPrompt] = useState("");
  const [selected, setSelected] = useState<string[]>(() =>
    findModel(catalog.models, catalog.default_model)?.available ? [catalog.default_model] : [],
  );
  const [params, setParams] = useState<RunParamsValue>({ temperature: null, maxTokens: null, thinking: false });
  const [judge, setJudge] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const prompts = useQuery({
    queryKey: queryKeys.prompts({ limit: 100, offset: 0, sort: "name", order: "asc" }),
    queryFn: ({ signal }) => listPrompts({ limit: 100, offset: 0, sort: "name", order: "asc" }, signal),
    enabled: source === "library",
  });
  const versions = useQuery({
    queryKey: queryKeys.versions(promptId, { limit: 100, offset: 0 }),
    queryFn: ({ signal }) => listVersions(promptId, { limit: 100, offset: 0 }, signal),
    enabled: source === "library" && promptId !== "",
  });

  const selectedModels = selected
    .map((id) => findModel(catalog.models, id))
    .filter((model): model is ModelInfo => model !== undefined);
  const caps = combineCapabilities(selectedModels, limits.max_output_tokens);
  // Every case makes one generation call per model, plus one judge call per LLM judge assertion
  // (the server counts both against max_eval_calls).
  const judgeAssertions = suite.cases.reduce(
    (count, testCase) => count + testCase.assertions.filter((assertion) => assertion.type === "llm_judge").length,
    0,
  );
  const generationCalls = suite.cases.length * selected.length;
  const judgeCalls = judgeAssertions * selected.length;
  const calls = generationCalls + judgeCalls;
  const overCap = calls > limits.max_eval_calls;
  const chosenVersion = versionId || versions.data?.items[0]?.id || "";
  const usesJudge = suite.cases.some((testCase) => testCase.assertions.some((assertion) => assertion.type === "llm_judge"));

  const start = useMutation({
    mutationFn: (body: EvalCreate) => startEval(body),
    onSuccess: (run) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.evals() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.suites() });
      void navigate(`/evals/${run.id}`);
    },
  });

  const sourceError =
    !submitted
      ? null
      : source === "library" && !chosenVersion
        ? "Choose a library prompt."
        : source === "adhoc" && !prompt
          ? "Enter a user prompt."
          : null;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (suite.cases.length === 0 || selected.length === 0 || overCap || !paramsAreValid(params, caps.maxOutputTokens)) return;
    if (source === "library" ? !chosenVersion : !prompt) return;
    start.mutate({
      suite_id: suite.id,
      ...(source === "library" ? { prompt_version_id: chosenVersion } : { system: system || null, prompt }),
      models: selected,
      temperature: caps.supportsTemperature ? params.temperature : null,
      max_tokens: params.maxTokens,
      thinking: caps.supportsThinking && params.thinking,
      judge_model: judge || null,
    });
  };

  return (
    <Card title="Run evaluation" description="Runs every case against each selected model in the background.">
      <form className="space-y-5" noValidate onSubmit={submit}>
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-fg">Prompt source</legend>
          <div className="flex flex-wrap gap-4">
            {(
              [
                { value: "library", label: "Library prompt" },
                { value: "adhoc", label: "Ad-hoc" },
              ] as const
            ).map((option) => (
              <label key={option.value} className="inline-flex cursor-pointer items-center gap-2 text-sm">
                <input
                  type="radio"
                  name={sourceName}
                  value={option.value}
                  className="size-4 accent-accent"
                  checked={source === option.value}
                  onChange={() => setSource(option.value)}
                />
                {option.label}
              </label>
            ))}
          </div>
        </fieldset>

        {source === "library" ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <Select
              label="Prompt"
              value={promptId}
              error={sourceError}
              hint={prompts.isError ? "Prompts could not be loaded." : undefined}
              onChange={(event) => {
                setPromptId(event.target.value);
                setVersionId("");
              }}
            >
              <option value="">{prompts.isPending ? "Loading prompts…" : "Choose a prompt"}</option>
              {(prompts.data?.items ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </Select>
            <Select
              label="Version"
              value={chosenVersion}
              disabled={!promptId || versions.isPending}
              onChange={(event) => setVersionId(event.target.value)}
            >
              {!promptId ? <option value="">Choose a prompt first</option> : null}
              {(versions.data?.items ?? []).map((item, index) => (
                <option key={item.id} value={item.id}>
                  v{item.version}
                  {index === 0 ? " (latest)" : ""}
                  {item.notes ? ` · ${item.notes}` : ""}
                </option>
              ))}
            </Select>
          </div>
        ) : (
          <div className="grid gap-3">
            <TextArea label="System prompt" value={system} mono rows={2} autoGrow onChange={(event) => setSystem(event.target.value)} />
            <TextArea
              label="User prompt"
              value={prompt}
              mono
              rows={4}
              autoGrow
              error={sourceError}
              hint="Use {{variables}} that the cases provide."
              onChange={(event) => setPrompt(event.target.value)}
            />
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-2">
          <ModelMultiSelect models={catalog.models} value={selected} max={limits.max_eval_models} onChange={setSelected} />
          <div className="space-y-4">
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
            <ModelPicker
              label="Judge model"
              models={catalog.models}
              value={judge}
              emptyOption="Server default"
              hint={usesJudge ? "Used by LLM judge assertions that do not name their own judge." : "Only used by LLM judge assertions."}
              onChange={setJudge}
            />
          </div>
        </div>

        <p className={cn("text-sm font-medium", overCap ? "text-danger" : "text-fg")} aria-live="polite">
          {suite.cases.length} {suite.cases.length === 1 ? "case" : "cases"} x {selected.length}{" "}
          {selected.length === 1 ? "model" : "models"}
          {judgeCalls > 0 ? ` + ${judgeCalls} judge ${judgeCalls === 1 ? "call" : "calls"}` : ""} = {calls} /{" "}
          {limits.max_eval_calls} calls
        </p>
        {submitted && suite.cases.length === 0 ? <p className="text-sm text-danger">Add at least one case first.</p> : null}
        {submitted && selected.length === 0 ? <p className="text-sm text-danger">Select at least one model.</p> : null}
        {start.error ? <ErrorState error={start.error} title="The evaluation could not start" /> : null}

        <Button
          type="submit"
          variant="primary"
          icon={<FlaskConical aria-hidden="true" className="size-4" />}
          loading={start.isPending}
          disabled={overCap}
        >
          Run evaluation
        </Button>
      </form>
    </Card>
  );
}
