import { Braces } from "lucide-react";
import type { VariableInfo } from "../api/types";
import { TextArea } from "./ui/TextArea";

export interface VariablesFormProps {
  variables: readonly VariableInfo[];
  values: Record<string, string>;
  onChange: (name: string, value: string) => void;
  /** Names reported missing by the server; their fields are flagged. */
  missing?: readonly string[];
  disabled?: boolean;
}

/**
 * One labelled field per `{{variable}}` of the template. The placeholder shows
 * the default; empty fields are never sent, so defaults apply server-side.
 */
export function VariablesForm({ variables, values, onChange, missing = [], disabled = false }: VariablesFormProps) {
  if (variables.length === 0) {
    return (
      <p className="flex items-start gap-2 text-sm text-fg-muted">
        <Braces aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        <span>
          No variables yet. Write <code className="font-mono text-fg">{"{{name}}"}</code> or{" "}
          <code className="font-mono text-fg">{"{{name|default}}"}</code> in a prompt to add one.
        </span>
      </p>
    );
  }
  return (
    <div className="grid gap-3">
      {variables.map((variable) => {
        const isMissing = missing.includes(variable.name);
        return (
          <TextArea
            key={variable.name}
            label={<span className="font-mono break-all">{variable.name}</span>}
            labelAside={
              variable.required ? (
                <span className="shrink-0 text-xs font-medium text-warning">required</span>
              ) : (
                <span className="shrink-0 text-xs text-fg-muted">optional</span>
              )
            }
            value={values[variable.name] ?? ""}
            placeholder={variable.default ?? ""}
            rows={1}
            autoGrow
            maxHeight={240}
            disabled={disabled}
            aria-required={variable.required || undefined}
            error={isMissing ? "A value is required." : null}
            onChange={(event) => onChange(variable.name, event.target.value)}
          />
        );
      })}
    </div>
  );
}
