import { useId } from "react";
import type { ModelInfo } from "../api/types";
import { cn } from "../lib/cn";
import { groupModels } from "../lib/models";

export interface ModelMultiSelectProps {
  models: readonly ModelInfo[];
  value: readonly string[];
  onChange: (modelIds: string[]) => void;
  max: number;
  legend?: string;
  className?: string;
}

/**
 * Checkbox list of models grouped by provider. Unavailable models are disabled;
 * once `max` models are selected the remaining boxes are disabled too.
 */
export function ModelMultiSelect({ models, value, onChange, max, legend = "Models", className }: ModelMultiSelectProps) {
  const hintId = useId();
  const selected = new Set(value);
  const atMax = value.length >= max;

  const toggle = (id: string, checked: boolean) => {
    if (checked) {
      if (!selected.has(id) && !atMax) onChange([...value, id]);
    } else {
      onChange(value.filter((item) => item !== id));
    }
  };

  return (
    <fieldset className={cn("min-w-0", className)} aria-describedby={hintId}>
      <legend className="text-sm font-medium text-fg">{legend}</legend>
      <p id={hintId} className="mt-0.5 text-xs text-fg-muted">
        {value.length} of {max} selected{atMax ? " (maximum reached)" : ""}
      </p>
      <div className="mt-2 space-y-3">
        {groupModels(models).map((group) => (
          <div key={group.provider}>
            <p className="text-xs font-semibold tracking-wide text-fg-muted uppercase">{group.label}</p>
            <ul className="mt-1 grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-1">
              {group.models.map((model) => {
                const checked = selected.has(model.id);
                const disabled = !model.available || (!checked && atMax);
                return (
                  <li key={model.id}>
                    <label
                      className={cn(
                        "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm",
                        disabled ? "cursor-not-allowed text-fg-muted" : "cursor-pointer hover:bg-surface-muted",
                      )}
                    >
                      <input
                        type="checkbox"
                        className="size-4 shrink-0 accent-accent"
                        checked={checked}
                        disabled={disabled}
                        onChange={(event) => toggle(model.id, event.target.checked)}
                      />
                      <span className="min-w-0 break-words">
                        {model.display_name}
                        {model.available ? "" : " (no API key)"}
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </fieldset>
  );
}
