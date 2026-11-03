import { LoaderCircle } from "lucide-react";
import { cn } from "../../lib/cn";

export interface SpinnerProps {
  size?: "xs" | "sm" | "md";
  /** When set, the spinner is announced with this text; otherwise it is decorative. */
  label?: string;
  className?: string;
}

/** Rotating progress indicator (the rotation stops under `prefers-reduced-motion`). */
export function Spinner({ size = "md", label, className }: SpinnerProps) {
  const icon = (
    <LoaderCircle
      aria-hidden="true"
      className={cn("animate-spin", size === "xs" ? "size-3.5" : size === "sm" ? "size-4" : "size-5", className)}
    />
  );
  if (!label) return icon;
  return (
    <span role="status" className="inline-flex items-center gap-2">
      {icon}
      <span className="sr-only">{label}</span>
    </span>
  );
}
