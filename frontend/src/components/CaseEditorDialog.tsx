import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import { createCase, updateCase } from "../api/endpoints";
import { queryKeys } from "../api/queryKeys";
import type { Assertion, CaseInput, ID, ModelInfo, TestCase } from "../api/types";
import { useToast } from "../context/toast";
import { assertionToDraft, draftToAssertion, newAssertionDraft, type AssertionDraft } from "../lib/assertions";
import { VARIABLE_NAME } from "../lib/template";
import { AssertionEditor } from "./AssertionEditor";
import { Button } from "./ui/Button";
import { Dialog } from "./ui/Dialog";
import { ErrorState } from "./ui/ErrorState";
import { IconButton } from "./ui/IconButton";
import { TextField } from "./ui/TextField";

interface VariableRow {
  key: string;
  name: string;
  value: string;
}

let rowCounter = 0;
function newRow(name = "", value = ""): VariableRow {
  rowCounter += 1;
  return { key: `var-${rowCounter}`, name, value };
}

export interface CaseEditorDialogProps {
  suiteId: ID;
  /** Case being edited; omitted to add a new one. */
  testCase?: TestCase;
  models: readonly ModelInfo[];
  maxAssertions: number;
  onClose: () => void;
}

/** Validation messages for the variable rows (empty rows are ignored). */
function variableErrors(rows: readonly VariableRow[]): Record<string, string> {
  const errors: Record<string, string> = {};
  const seen = new Set<string>();
  for (const row of rows) {
    const name = row.name.trim();
    if (!name && !row.value) continue;
    if (!VARIABLE_NAME.test(name)) {
      errors[row.key] = "Use letters, digits and _ (not starting with a digit), up to 64 characters.";
    } else if (seen.has(name)) {
      errors[row.key] = "This variable is already defined.";
    }
    seen.add(name);
  }
  return errors;
}

/** The form content without React keys, for comparing against the opening state. */
function formSnapshot(name: string, rows: readonly VariableRow[], drafts: readonly AssertionDraft[]): string {
  return JSON.stringify({
    name,
    rows: rows.map((row) => [row.name, row.value]),
    drafts: drafts.map(({ key: _key, ...rest }) => rest),
  });
}

/** Add or edit a test case: name, variables (key/value rows) and assertions. Server 422 errors show in the form. */
export function CaseEditorDialog({ suiteId, testCase, models, maxAssertions, onClose }: CaseEditorDialogProps) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [name, setName] = useState(testCase?.name ?? "");
  const [rows, setRows] = useState<VariableRow[]>(() => {
    const entries = Object.entries(testCase?.variables ?? {});
    return entries.length > 0 ? entries.map(([key, value]) => newRow(key, value)) : [newRow()];
  });
  const [drafts, setDrafts] = useState<AssertionDraft[]>(() =>
    testCase && testCase.assertions.length > 0 ? testCase.assertions.map(assertionToDraft) : [newAssertionDraft()],
  );
  const [submitted, setSubmitted] = useState(false);
  // What the form held when it opened, to tell whether anything was typed since.
  const [pristine] = useState(() => formSnapshot(name, rows, drafts));
  const dirty = formSnapshot(name, rows, drafts) !== pristine;

  const mutation = useMutation({
    mutationFn: (body: CaseInput) => (testCase ? updateCase(suiteId, testCase.id, body) : createCase(suiteId, body)),
    onSuccess: async (saved) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.suite(suiteId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.suites() }),
      ]);
      toast({ tone: "success", title: testCase ? `Saved "${saved.name}"` : `Added "${saved.name}"` });
      onClose();
    },
  });

  const nameError = submitted && !name.trim() ? "Enter a case name." : name.length > 200 ? "At most 200 characters." : null;
  const rowErrors = variableErrors(rows);
  const draftResults = drafts.map(draftToAssertion);
  const serverError = mutation.error instanceof ApiError ? mutation.error : null;
  const serverAssertionIndex =
    serverError?.code === "invalid_assertion" && typeof serverError.details?.assertion_index === "number"
      ? serverError.details.assertion_index
      : null;
  const serverReason = typeof serverError?.details?.reason === "string" ? serverError.details.reason : null;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (!name.trim() || name.length > 200 || Object.keys(rowErrors).length > 0) return;
    const assertions: Assertion[] = [];
    for (const result of draftResults) {
      if (!result.ok) return;
      assertions.push(result.assertion);
    }
    const variables: Record<string, string> = {};
    for (const row of rows) {
      const key = row.name.trim();
      if (key) variables[key] = row.value;
    }
    mutation.mutate({ name: name.trim(), variables, assertions });
  };

  const formId = "case-editor-form";
  return (
    <Dialog
      open
      onClose={onClose}
      closeOnBackdrop={!dirty}
      size="lg"
      title={testCase ? "Edit test case" : "Add test case"}
      description="Variables fill the prompt template; every assertion must pass for the case to pass."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form={formId} variant="primary" loading={mutation.isPending}>
            {testCase ? "Save case" : "Add case"}
          </Button>
        </>
      }
    >
      <form id={formId} noValidate onSubmit={submit} className="space-y-5">
        <TextField
          label="Case name"
          value={name}
          maxLength={200}
          required
          error={nameError}
          data-autofocus="true"
          onChange={(event) => setName(event.target.value)}
        />

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-fg">Variables</legend>
          {rows.map((row, index) => (
            <div key={row.key} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)_auto] items-start gap-2">
              <TextField
                label={`Variable ${index + 1} name`}
                value={row.name}
                inputClassName="font-mono"
                error={rowErrors[row.key] ?? null}
                onChange={(event) =>
                  setRows((current) =>
                    current.map((item) => (item.key === row.key ? { ...item, name: event.target.value } : item)),
                  )
                }
              />
              <TextField
                label={`Variable ${index + 1} value`}
                value={row.value}
                onChange={(event) =>
                  setRows((current) =>
                    current.map((item) => (item.key === row.key ? { ...item, value: event.target.value } : item)),
                  )
                }
              />
              <IconButton
                label={`Remove variable ${index + 1}`}
                icon={<Trash2 aria-hidden="true" className="size-4" />}
                variant="secondary"
                className="mt-7"
                onClick={() =>
                  setRows((current) => {
                    const next = current.filter((item) => item.key !== row.key);
                    return next.length > 0 ? next : [newRow()];
                  })
                }
              />
            </div>
          ))}
          <Button size="sm" icon={<Plus aria-hidden="true" className="size-4" />} onClick={() => setRows((current) => [...current, newRow()])}>
            Add variable
          </Button>
        </fieldset>

        <div className="space-y-3">
          <h3 className="text-sm font-medium text-fg">Assertions</h3>
          {drafts.map((draft, index) => {
            const result = draftResults[index];
            const clientError = submitted && result && !result.ok ? result.error : null;
            const serverMessage = serverAssertionIndex === index ? (serverReason ?? serverError?.message ?? null) : null;
            return (
              <AssertionEditor
                key={draft.key}
                draft={draft}
                index={index}
                models={models}
                canRemove={drafts.length > 1}
                error={clientError ?? serverMessage}
                onChange={(next) => setDrafts((current) => current.map((item) => (item.key === draft.key ? next : item)))}
                onRemove={() => setDrafts((current) => current.filter((item) => item.key !== draft.key))}
              />
            );
          })}
          <Button
            size="sm"
            icon={<Plus aria-hidden="true" className="size-4" />}
            disabled={drafts.length >= maxAssertions}
            onClick={() => setDrafts((current) => [...current, newAssertionDraft()])}
          >
            Add assertion
          </Button>
        </div>

        {serverError ? <ErrorState error={serverError} title="The case could not be saved" compact /> : null}
      </form>
    </Dialog>
  );
}
