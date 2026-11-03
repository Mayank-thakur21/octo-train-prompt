import { useId, type ReactNode } from "react";
import { cn } from "../../lib/cn";
import { HINT_CLASSES, LABEL_CLASSES } from "./styles";

export interface SliderProps {
  label: ReactNode;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  disabled?: boolean;
  hint?: ReactNode;
  /** Formats the visible value (defaults to the number itself). */
  format?: (value: number) => string;
  className?: string;
}

/** Labelled range input that shows its current value. */
export function Slider({ label, value, min, max, step, onChange, disabled = false, hint, format, className }: SliderProps) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const display = format ? format(value) : String(value);
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={id} className={LABEL_CLASSES}>
          {label}
        </label>
        <output htmlFor={id} className="font-mono text-sm text-fg-muted tabular-nums">
          {display}
        </output>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        aria-describedby={hintId}
        aria-valuetext={display}
        onChange={(event) => onChange(Number(event.target.value))}
        className="h-2 w-full cursor-pointer accent-accent disabled:cursor-not-allowed disabled:opacity-50"
      />
      {hint ? (
        <p id={hintId} className={HINT_CLASSES}>
          {hint}
        </p>
      ) : null}
    </div>
  );
}
