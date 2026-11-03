import { useState } from "react";
import type { BuiltinTemplate } from "../api/types";
import { useTemplates } from "../hooks/queries";
import { Badge } from "./ui/Badge";
import { Dialog } from "./ui/Dialog";
import { EmptyState } from "./ui/EmptyState";
import { ErrorState } from "./ui/ErrorState";
import { LoadingBlock } from "./ui/Skeleton";
import { TextField } from "./ui/TextField";

export interface TemplatePickerDialogProps {
  onPick: (template: BuiltinTemplate) => void;
  onClose: () => void;
}

/** Lists the built-in templates (`GET /api/templates`); choosing one fills system and user prompt. */
export function TemplatePickerDialog({ onPick, onClose }: TemplatePickerDialogProps) {
  const templates = useTemplates();
  const [filter, setFilter] = useState("");
  const needle = filter.trim().toLowerCase();
  const items = (templates.data?.templates ?? []).filter(
    (template) =>
      !needle ||
      template.name.toLowerCase().includes(needle) ||
      template.description.toLowerCase().includes(needle) ||
      template.tags.some((tag) => tag.includes(needle)),
  );

  return (
    <Dialog open onClose={onClose} size="lg" title="Templates" description="Start from a built-in prompt template.">
      <div className="space-y-3">
        <TextField
          label="Filter templates"
          type="search"
          value={filter}
          data-autofocus="true"
          onChange={(event) => setFilter(event.target.value)}
        />
        {templates.isPending ? (
          <LoadingBlock label="Loading templates…" lines={4} />
        ) : templates.isError ? (
          <ErrorState error={templates.error} onRetry={() => void templates.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState title="No templates match" description="Try another search term." />
        ) : (
          <ul className="grid gap-2 sm:grid-cols-2">
            {items.map((template) => (
              <li key={template.id}>
                <button
                  type="button"
                  onClick={() => onPick(template)}
                  className="flex h-full w-full flex-col items-start gap-1.5 rounded-lg border border-line bg-surface p-3 text-left hover:border-accent hover:bg-accent-soft"
                >
                  <span className="font-medium text-fg">{template.name}</span>
                  <span className="text-sm text-fg-muted">{template.description}</span>
                  <span className="flex flex-wrap gap-1">
                    {template.tags.map((tag) => (
                      <Badge key={tag}>{tag}</Badge>
                    ))}
                    {template.variables.map((variable) => (
                      <Badge key={`var-${variable.name}`} tone="accent">
                        {`{{${variable.name}}}`}
                      </Badge>
                    ))}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Dialog>
  );
}
