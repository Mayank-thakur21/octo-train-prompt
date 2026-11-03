import type { ModelInfo } from "../api/types";
import { groupModels } from "../lib/models";
import { Select } from "./ui/Select";

export interface ModelPickerProps {
  models: readonly ModelInfo[];
  value: string;
  onChange: (modelId: string) => void;
  label?: string;
  disabled?: boolean;
  hint?: string;
  /** Adds a first option with an empty value (e.g. "Default judge"). */
  emptyOption?: string;
  className?: string;
}

/** Model `<select>` with one `<optgroup>` per provider; models without an API key are disabled. */
export function ModelPicker({
  models,
  value,
  onChange,
  label = "Model",
  disabled = false,
  hint,
  emptyOption,
  className,
}: ModelPickerProps) {
  return (
    <Select
      label={label}
      value={value}
      disabled={disabled}
      hint={hint}
      className={className}
      onChange={(event) => onChange(event.target.value)}
    >
      {emptyOption !== undefined ? <option value="">{emptyOption}</option> : null}
      {groupModels(models).map((group) => (
        <optgroup key={group.provider} label={group.label}>
          {group.models.map((model) => (
            <option key={model.id} value={model.id} disabled={!model.available}>
              {model.display_name}
              {model.available ? "" : " (no API key)"}
            </option>
          ))}
        </optgroup>
      ))}
    </Select>
  );
}
