import { useId, type ComponentProps, type ReactNode } from "react";
import { cn } from "../../lib/cn";
import { describedBy, ERROR_TEXT_CLASSES, HINT_CLASSES, inputClasses, LABEL_CLASSES } from "./styles";

export interface TextFieldProps extends Omit<ComponentProps<"input">, "className"> {
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null | undefined;
  /** Extra content rendered next to the label (e.g. a "required" marker). */
  labelAside?: ReactNode;
  className?: string;
  inputClassName?: string;
}

/** Labelled `<input>` with optional hint and error text wired through `aria-describedby`. */
export function TextField({
  label,
  hint,
  error,
  labelAside,
  id,
  className,
  inputClassName,
  ...rest
}: TextFieldProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const hintId = hint ? `${inputId}-hint` : null;
  const errorId = error ? `${inputId}-error` : null;
  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={inputId} className={LABEL_CLASSES}>
          {label}
        </label>
        {labelAside}
      </div>
      <input
        id={inputId}
        aria-describedby={describedBy(hintId, errorId)}
        aria-invalid={error ? true : undefined}
        className={inputClasses(Boolean(error), cn("h-10", inputClassName))}
        {...rest}
      />
      {hint ? (
        <p id={hintId ?? undefined} className={HINT_CLASSES}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId ?? undefined} className={ERROR_TEXT_CLASSES}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
