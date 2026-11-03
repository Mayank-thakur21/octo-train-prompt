import { useId, type ReactNode } from "react";
import { cn } from "../../lib/cn";

export interface TooltipProps {
  content: ReactNode;
  /** Receives the tooltip id so the trigger can reference it with `aria-describedby`. */
  children: (tooltipId: string) => ReactNode;
  className?: string;
}

/** Hover/focus tooltip. The trigger must be focusable and use the provided id for `aria-describedby`. */
export function Tooltip({ content, children, className }: TooltipProps) {
  const id = useId();
  return (
    <span className={cn("group relative inline-flex", className)}>
      {children(id)}
      <span
        role="tooltip"
        id={id}
        className={cn(
          "pointer-events-none absolute bottom-full left-0 z-40 mb-1.5 w-max max-w-64 rounded-md bg-fg px-2 py-1 text-xs text-canvas shadow-lg",
          "invisible opacity-0 transition-opacity group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100",
        )}
      >
        {content}
      </span>
    </span>
  );
}
