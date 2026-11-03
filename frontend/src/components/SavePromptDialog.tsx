import { useState, type FormEvent } from "react";
import { parseTags } from "../lib/tags";
import { Button } from "./ui/Button";
import { Dialog } from "./ui/Dialog";
import { ErrorState } from "./ui/ErrorState";
import { TextArea } from "./ui/TextArea";
import { TextField } from "./ui/TextField";

export interface SavePromptValues {
  name: string;
  description: string;
  tags: string[];
  system: string;
  prompt: string;
  notes: string;
}

export interface SavePromptDialogProps {
  /** `create` = new library prompt, `version` = new version of an existing prompt (notes only). */
  mode: "create" | "version";
  /** Also edit the system/user prompt (used by "New prompt" in the Library). */
  withContent?: boolean;
  promptName?: string;
  initial?: Partial<SavePromptValues>;
  pending: boolean;
  error: unknown;
  maxTags: number;
  onSubmit: (values: SavePromptValues) => void;
  onClose: () => void;
}

/** Dialog for "Save as prompt", "New prompt" and "Save new version". */
export function SavePromptDialog({
  mode,
  withContent = false,
  promptName,
  initial,
  pending,
  error,
  maxTags,
  onSubmit,
  onClose,
}: SavePromptDialogProps) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [tagsText, setTagsText] = useState((initial?.tags ?? []).join(", "));
  const [system, setSystem] = useState(initial?.system ?? "");
  const [prompt, setPrompt] = useState(initial?.prompt ?? "");
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [submitted, setSubmitted] = useState(false);

  const dirty =
    name !== (initial?.name ?? "") ||
    description !== (initial?.description ?? "") ||
    tagsText !== (initial?.tags ?? []).join(", ") ||
    system !== (initial?.system ?? "") ||
    prompt !== (initial?.prompt ?? "") ||
    notes !== (initial?.notes ?? "");
  const tags = parseTags(tagsText);
  const nameError =
    mode === "create" && submitted && !name.trim()
      ? "Enter a name."
      : name.trim().length > 120
        ? "At most 120 characters."
        : null;
  const tagsError = tags.length > maxTags ? `At most ${maxTags} tags.` : null;
  const promptError = withContent && submitted && !prompt ? "Enter the user prompt." : null;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (mode === "create" && (!name.trim() || name.trim().length > 120 || tagsError)) return;
    if (withContent && !prompt) return;
    onSubmit({ name: name.trim(), description: description.trim(), tags, system, prompt, notes: notes.trim() });
  };

  const formId = `save-prompt-${mode}`;
  const title = mode === "version" ? "Save new version" : withContent ? "New prompt" : "Save as prompt";
  return (
    <Dialog
      open
      onClose={onClose}
      closeOnBackdrop={!dirty}
      size={withContent ? "lg" : "md"}
      title={title}
      description={
        mode === "version"
          ? `Adds a new immutable version to "${promptName ?? "this prompt"}" with the current templates and settings.`
          : "Stores the prompt in your library as version 1."
      }
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form={formId} variant="primary" loading={pending}>
            {mode === "version" ? "Save version" : "Save prompt"}
          </Button>
        </>
      }
    >
      <form id={formId} noValidate onSubmit={submit} className="space-y-4">
        {mode === "create" ? (
          <>
            <TextField
              label="Name"
              value={name}
              maxLength={120}
              required
              error={nameError}
              data-autofocus="true"
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
              hint="Comma separated, e.g. writing, support"
              error={tagsError}
              onChange={(event) => setTagsText(event.target.value)}
            />
            {withContent ? (
              <>
                <TextArea
                  label="System prompt"
                  value={system}
                  mono
                  rows={3}
                  autoGrow
                  onChange={(event) => setSystem(event.target.value)}
                />
                <TextArea
                  label="User prompt"
                  value={prompt}
                  mono
                  rows={5}
                  autoGrow
                  required
                  error={promptError}
                  onChange={(event) => setPrompt(event.target.value)}
                />
              </>
            ) : null}
          </>
        ) : null}
        <TextField
          label="Version notes"
          value={notes}
          maxLength={500}
          hint="Optional: what changed in this version."
          data-autofocus={mode === "version" ? "true" : undefined}
          onChange={(event) => setNotes(event.target.value)}
        />
        {error ? <ErrorState error={error} compact /> : null}
      </form>
    </Dialog>
  );
}
