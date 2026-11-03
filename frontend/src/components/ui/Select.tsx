import { useId, type ComponentProps, type ReactNode } from "react";
import { cn } from "../../lib/cn";
import { describedBy, ERROR_TEXT_CLASSES, HINT_CLASSES, inputClasses, LABEL_CLASSES } from "./styles";

export interface SelectProps extends Omit<ComponentProps<"select">, "className"> {
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null | undefined;
  className?: string;
  selectClassName?: string;
}

/** Labelled native `<select>`; options are passed as children. */
export function Select({ label, hint, error, id, className, selectClassName, children, ...rest }: SelectProps) {
  const autoId = useId();
  const selectId = id ?? autoId;
  const hintId = hint ? `${selectId}-hint` : null;
  const errorId = error ? `${selectId}-error` : null;
  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      <label htmlFor={selectId} className={LABEL_CLASSES}>
        {label}
      </label>
      <select
        id={selectId}
        aria-describedby={describedBy(hintId, errorId)}
        aria-invalid={error ? true : undefined}
        className={inputClasses(Boolean(error), cn("h-10", selectClassName), { padding: "py-2 pl-3 pr-8" })}
        {...rest}
      >
        {children}
      </select>
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
