import { useId, useState } from "react";
import { formatNumber } from "../lib/format";
import type { RunParamsValue } from "../lib/params";
import { Slider } from "./ui/Slider";
import { Switch } from "./ui/Switch";
import { TextField } from "./ui/TextField";

export interface RunParamsFormProps {
  value: RunParamsValue;
  onChange: (value: RunParamsValue) => void;
  supportsTemperature: boolean;
  supportsThinking: boolean;
  thinkingAlwaysOn: boolean;
  maxOutputTokens: number;
  /** Shown as the Max tokens placeholder when the field is empty. */
  defaultMaxTokens: number;
  /** Hint used when temperature is supported by only some of several models. */
  temperatureNote?: string;
  /** `id` of the Max tokens input, so a form can focus it when the value is invalid. */
  maxTokensId?: string;
  disabled?: boolean;
}

/** Temperature, Max tokens and Show thinking controls shared by Playground, Compare and evaluations. */
export function RunParamsForm({
  value,
  onChange,
  supportsTemperature,
  supportsThinking,
  thinkingAlwaysOn,
  maxOutputTokens,
  defaultMaxTokens,
  temperatureNote,
  maxTokensId,
  disabled = false,
}: RunParamsFormProps) {
  const defaultId = useId();
  const [lastTemperature, setLastTemperature] = useState(value.temperature ?? 1);
  const useDefault = value.temperature === null;
  const maxTokensError =
    value.maxTokens !== null && (value.maxTokens < 1 || value.maxTokens > maxOutputTokens)
      ? `Enter a value between 1 and ${formatNumber(maxOutputTokens)}.`
      : null;

  const temperatureHint = !supportsTemperature ? "Not supported by this model" : temperatureNote;
  const thinkingHint = !supportsThinking
    ? "Not supported by this model"
    : thinkingAlwaysOn
      ? "This model always thinks; the switch shows its thinking summary."
      : undefined;

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Slider
          label="Temperature"
          min={0}
          max={2}
          step={0.1}
          value={value.temperature ?? lastTemperature}
          format={(v) => v.toFixed(1)}
          disabled={disabled || !supportsTemperature || useDefault}
          hint={temperatureHint}
          onChange={(next) => {
            const rounded = Math.round(next * 10) / 10;
            setLastTemperature(rounded);
            onChange({ ...value, temperature: rounded });
          }}
        />
        <label htmlFor={defaultId} className="inline-flex cursor-pointer items-center gap-2 text-sm text-fg">
          <input
            id={defaultId}
            type="checkbox"
            className="size-4 accent-accent"
            checked={useDefault}
            disabled={disabled || !supportsTemperature}
            onChange={(event) =>
              onChange({ ...value, temperature: event.target.checked ? null : lastTemperature })
            }
          />
          Use model default
        </label>
      </div>
      {/*
        An out-of-range value is kept as typed and reported (the form's Run
        refuses it). It is not clamped on blur: that silently changed the value
        and moved the layout under the pointer, so a click on Run was lost.
        The error replaces the hint in the same line, so the height stays put.
      */}
      <TextField
        id={maxTokensId}
        label="Max tokens"
        type="number"
        inputMode="numeric"
        min={1}
        max={maxOutputTokens}
        step={1}
        disabled={disabled}
        value={value.maxTokens ?? ""}
        placeholder={`Default (${formatNumber(defaultMaxTokens)})`}
        hint={maxTokensError ? undefined : `1 to ${formatNumber(maxOutputTokens)}`}
        error={maxTokensError}
        onChange={(event) => {
          const raw = event.target.value;
          onChange({ ...value, maxTokens: raw === "" ? null : Math.trunc(Number(raw)) });
        }}
        onBlur={() => {
          if (value.maxTokens !== null && Number.isNaN(value.maxTokens)) onChange({ ...value, maxTokens: null });
        }}
      />
      <Switch
        label="Show thinking"
        checked={supportsThinking && value.thinking}
        disabled={disabled || !supportsThinking}
        hint={thinkingHint}
        onChange={(checked) => onChange({ ...value, thinking: checked })}
      />
    </div>
  );
}
