import { useId, useLayoutEffect, useRef, type ComponentProps, type ReactNode } from "react";
import { cn } from "../../lib/cn";
import { describedBy, ERROR_TEXT_CLASSES, HINT_CLASSES, inputClasses, LABEL_CLASSES } from "./styles";

export interface TextAreaProps extends Omit<ComponentProps<"textarea">, "className" | "value"> {
  label: ReactNode;
  value: string;
  hint?: ReactNode;
  error?: string | null | undefined;
  labelAside?: ReactNode;
  /** Monospace font for prompt/code editing. */
  mono?: boolean;
  /** Grow with the content (up to `maxHeight` pixels, then scroll). */
  autoGrow?: boolean;
  maxHeight?: number;
  className?: string;
  textareaClassName?: string;
}

/** Labelled `<textarea>` with optional auto-grow, hint and error text. */
export function TextArea({
  label,
  value,
  hint,
  error,
  labelAside,
  mono = false,
  autoGrow = false,
  maxHeight = 520,
  id,
  className,
  textareaClassName,
  ...rest
}: TextAreaProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  const hintId = hint ? `${fieldId}-hint` : null;
  const errorId = error ? `${fieldId}-error` : null;
  const ref = useRef<HTMLTextAreaElement>(null);

  // Resize after every value change. Inline styles are set through the CSSOM, which a strict CSP allows.
  useLayoutEffect(() => {
    const element = ref.current;
    if (!autoGrow || !element) return;
    element.style.height = "auto";
    const next = Math.min(element.scrollHeight + 2, maxHeight);
    element.style.height = `${next}px`;
    element.style.overflowY = element.scrollHeight + 2 > maxHeight ? "auto" : "hidden";
  }, [value, autoGrow, maxHeight]);

  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={fieldId} className={LABEL_CLASSES}>
          {label}
        </label>
        {labelAside}
      </div>
      <textarea
        ref={ref}
        id={fieldId}
        value={value}
        aria-describedby={describedBy(hintId, errorId)}
        aria-invalid={error ? true : undefined}
        spellCheck={mono ? false : undefined}
        className={inputClasses(Boolean(error), cn("resize-y leading-relaxed", textareaClassName), { mono })}
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
