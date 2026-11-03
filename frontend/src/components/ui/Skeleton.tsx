import { cn } from "../../lib/cn";

/** Decorative placeholder block (pulses unless reduced motion is requested). */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn("animate-pulse rounded-md bg-surface-muted", className)} />;
}

export interface LoadingBlockProps {
  /** Announced to assistive technology. */
  label?: string;
  lines?: number;
  className?: string;
}

/** Skeleton lines plus a polite, screen-reader-only loading message. */
export function LoadingBlock({ label = "Loading…", lines = 3, className }: LoadingBlockProps) {
  return (
    <div role="status" aria-live="polite" className={cn("space-y-2.5", className)}>
      <span className="sr-only">{label}</span>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton key={index} className={cn("h-4", index === lines - 1 ? "w-2/3" : "w-full")} />
      ))}
    </div>
  );
}

/** Skeleton for a full page while its data or code loads. */
export function PageSkeleton() {
  return (
    <div role="status" aria-live="polite" className="space-y-6">
      <span className="sr-only">Loading page…</span>
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-4 w-80 max-w-full" />
      <div className="grid gap-4 md:grid-cols-2">
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
      </div>
    </div>
  );
}
