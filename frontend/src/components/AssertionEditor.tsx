import { Trash2 } from "lucide-react";
import { useId } from "react";
import type { AssertionType, ModelInfo } from "../api/types";
import { ASSERTION_TYPES, changeDraftType, type AssertionDraft } from "../lib/assertions";
import { ModelPicker } from "./ModelPicker";
import { IconButton } from "./ui/IconButton";
import { Select } from "./ui/Select";
import { TextArea } from "./ui/TextArea";
import { TextField } from "./ui/TextField";

export interface AssertionEditorProps {
  draft: AssertionDraft;
  index: number;
  onChange: (draft: AssertionDraft) => void;
  onRemove: () => void;
  canRemove: boolean;
  models: readonly ModelInfo[];
  /** Validation message (client-side or from the server's `invalid_assertion`). */
  error?: string | null;
}

function Checkbox({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  const id = useId();
  return (
    <label htmlFor={id} className="inline-flex cursor-pointer items-center gap-2 text-sm text-fg">
      <input
        id={id}
        type="checkbox"
        className="size-4 accent-accent"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      {label}
    </label>
  );
}

const FLAG_LABELS: Array<{ flag: string; label: string }> = [
  { flag: "i", label: "i (ignore case)" },
  { flag: "m", label: "m (multiline)" },
  { flag: "s", label: "s (dot matches newline)" },
];

/** Editor for one assertion; shows the fields of the selected type only. */
export function AssertionEditor({ draft, index, onChange, onRemove, canRemove, models, error }: AssertionEditorProps) {
  const errorId = useId();
  const set = (patch: Partial<AssertionDraft>) => onChange({ ...draft, ...patch });
  const number = index + 1;

  const fields = (() => {
    switch (draft.type) {
      case "contains":
      case "not_contains":
      case "equals":
      case "starts_with":
        return (
          <>
            <TextArea
              label="Expected text"
              value={draft.value}
              rows={1}
              autoGrow
              maxHeight={200}
              onChange={(event) => set({ value: event.target.value })}
            />
            <div className="flex flex-wrap gap-4">
              <Checkbox label="Case sensitive" checked={draft.caseSensitive} onChange={(value) => set({ caseSensitive: value })} />
              {draft.type === "equals" || draft.type === "starts_with" ? (
                <Checkbox label="Trim whitespace" checked={draft.trim} onChange={(value) => set({ trim: value })} />
              ) : null}
            </div>
          </>
        );
      case "regex":
        return (
          <>
            <TextField
              label="Pattern"
              value={draft.pattern}
              inputClassName="font-mono"
              hint="Python regular expression syntax, searched anywhere in the output."
              onChange={(event) => set({ pattern: event.target.value })}
            />
            <fieldset className="flex flex-wrap gap-4">
              <legend className="mb-1 text-sm font-medium text-fg">Flags</legend>
              {FLAG_LABELS.map(({ flag, label }) => (
                <Checkbox
                  key={flag}
                  label={label}
                  checked={draft.flags.includes(flag)}
                  onChange={(checked) =>
                    set({
                      flags: ["i", "m", "s"]
                        .filter((item) => (item === flag ? checked : draft.flags.includes(item)))
                        .join(""),
                    })
                  }
                />
              ))}
            </fieldset>
          </>
        );
      case "max_chars":
      case "min_chars":
        return (
          <TextField
            label={draft.type === "max_chars" ? "Maximum characters" : "Minimum characters"}
            type="number"
            min={0}
            step={1}
            inputMode="numeric"
            value={draft.chars}
            onChange={(event) => set({ chars: event.target.value })}
          />
        );
      case "json_valid":
        return <p className="text-sm text-fg-muted">Passes when the output parses as JSON (code fences are ignored).</p>;
      case "json_schema":
        return (
          <TextArea
            label="JSON schema"
            mono
            rows={5}
            autoGrow
            maxHeight={320}
            value={draft.schemaText}
            hint="Supported keywords: type, properties, required, additionalProperties, items, enum, const, lengths, ranges, pattern."
            onChange={(event) => set({ schemaText: event.target.value })}
          />
        );
      case "llm_judge":
        return (
          <>
            <TextArea
              label="Rubric"
              rows={3}
              autoGrow
              maxHeight={260}
              value={draft.rubric}
              hint="Describe what a good answer contains. The judge scores 1 to 5."
              onChange={(event) => set({ rubric: event.target.value })}
            />
            <div className="grid gap-3 sm:grid-cols-2">
              <Select
                label="Pass threshold"
                value={String(draft.threshold)}
                onChange={(event) => set({ threshold: Number(event.target.value) })}
              >
                {[1, 2, 3, 4, 5].map((score) => (
                  <option key={score} value={score}>
                    Score {score} or higher
                  </option>
                ))}
              </Select>
              <ModelPicker
                label="Judge model"
                models={models}
                value={draft.judgeModel ?? ""}
                emptyOption="Evaluation default"
                onChange={(value) => set({ judgeModel: value || null })}
              />
            </div>
          </>
        );
    }
  })();

  return (
    <fieldset
      aria-describedby={error ? errorId : undefined}
      className="min-w-0 space-y-3 rounded-lg border border-line bg-surface-muted/50 p-3"
    >
      <legend className="sr-only">Assertion {number}</legend>
      <div className="flex items-end gap-2">
        <Select
          label={`Assertion ${number} type`}
          className="flex-1"
          value={draft.type}
          onChange={(event) => onChange(changeDraftType(draft, event.target.value as AssertionType))}
        >
          {ASSERTION_TYPES.map((item) => (
            <option key={item.type} value={item.type}>
              {item.label}
            </option>
          ))}
        </Select>
        <IconButton
          label={`Remove assertion ${number}`}
          icon={<Trash2 aria-hidden="true" className="size-4" />}
          variant="secondary"
          disabled={!canRemove}
          onClick={onRemove}
        />
      </div>
      {fields}
      {error ? (
        <p id={errorId} role="alert" className="text-xs font-medium text-danger">
          {error}
        </p>
      ) : null}
    </fieldset>
  );
}
