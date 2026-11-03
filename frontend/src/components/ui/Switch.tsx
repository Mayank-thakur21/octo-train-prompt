import { useId, type ReactNode } from "react";
import { cn } from "../../lib/cn";
import { HINT_CLASSES } from "./styles";

export interface SwitchProps {
  label: ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  hint?: ReactNode;
  className?: string;
}

/** On/off switch: a native checkbox with `role="switch"`, so it is keyboard and screen-reader friendly. */
export function Switch({ label, checked, onChange, disabled = false, hint, className }: SwitchProps) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <label htmlFor={id} className={cn("inline-flex items-center gap-3", disabled ? "cursor-not-allowed" : "cursor-pointer")}>
        <input
          id={id}
          type="checkbox"
          role="switch"
          className="peer sr-only"
          checked={checked}
          disabled={disabled}
          aria-describedby={hintId}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span
          aria-hidden="true"
          className={cn(
            "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border border-line-strong bg-surface-muted transition-colors",
            "peer-checked:border-accent peer-checked:bg-accent peer-disabled:opacity-50",
            "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ring",
            "peer-checked:[&>span]:translate-x-5 peer-checked:[&>span]:bg-white",
          )}
        >
          <span className="ml-0.5 size-4.5 rounded-full bg-fg-muted shadow-sm transition-transform" />
        </span>
        <span className="text-sm font-medium text-fg">{label}</span>
      </label>
      {hint ? (
        <p id={hintId} className={HINT_CLASSES}>
          {hint}
        </p>
      ) : null}
    </div>
  );
}
