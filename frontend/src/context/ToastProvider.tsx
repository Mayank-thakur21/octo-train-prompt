import { CircleAlert, CircleCheck, Info, TriangleAlert, X } from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FocusEvent,
  type ReactNode,
} from "react";
import { Link } from "react-router";
import { cn } from "../lib/cn";
import { ToastContext, type Toast, type ToastInput, type ToastValue } from "./toast";

/** Visible toasts at most; older ones are dropped first. */
const MAX_TOASTS = 4;
const DURATION_MS = 5000;
const ERROR_DURATION_MS = 8000;

const TONE_STYLES: Record<Toast["tone"], { className: string; icon: ReactNode }> = {
  success: { className: "border-success/50", icon: <CircleCheck aria-hidden="true" className="size-5 text-success" /> },
  error: { className: "border-danger/50", icon: <CircleAlert aria-hidden="true" className="size-5 text-danger" /> },
  warning: { className: "border-warning/50", icon: <TriangleAlert aria-hidden="true" className="size-5 text-warning" /> },
  info: { className: "border-info/50", icon: <Info aria-hidden="true" className="size-5 text-info" /> },
};

/**
 * One toast. Its dismiss timer pauses while the pointer is over it or focus is
 * inside it, and restarts when both leave (WCAG 2.2.1), so a keyboard user can
 * reach and use its link. If the toast disappears while focused, focus goes
 * back to where it came from instead of falling to the page body.
 */
function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: string) => void }) {
  const style = TONE_STYLES[toast.tone];
  const containerRef = useRef<HTMLDivElement>(null);
  const returnFocusTo = useRef<HTMLElement | null>(null);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const paused = hovered || focused;

  useEffect(() => {
    if (paused) return undefined;
    const timer = window.setTimeout(
      () => onDismiss(toast.id),
      toast.tone === "error" ? ERROR_DURATION_MS : DURATION_MS,
    );
    return () => window.clearTimeout(timer);
  }, [toast, onDismiss, paused]);

  // Runs before the node leaves the DOM, while it can still tell that it holds focus.
  useLayoutEffect(() => {
    const container = containerRef.current;
    return () => {
      if (!container?.contains(document.activeElement)) return;
      const target = returnFocusTo.current?.isConnected ? returnFocusTo.current : document.getElementById("main");
      target?.focus();
    };
  }, []);

  const onFocus = (event: FocusEvent<HTMLDivElement>) => {
    const from = event.relatedTarget;
    if (!event.currentTarget.contains(from)) returnFocusTo.current = from instanceof HTMLElement ? from : null;
    setFocused(true);
  };
  const onBlur = (event: FocusEvent<HTMLDivElement>) => {
    if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false);
  };

  return (
    <div
      ref={containerRef}
      data-testid="toast"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={onFocus}
      onBlur={onBlur}
      className={cn(
        "pointer-events-auto flex w-full items-start gap-3 rounded-lg border bg-surface p-3 text-sm text-fg shadow-lg",
        style.className,
      )}
    >
      <span className="mt-0.5 shrink-0">{style.icon}</span>
      <div className="min-w-0 flex-1">
        <p className="font-medium break-words">{toast.title}</p>
        {toast.description ? <p className="mt-0.5 break-words text-fg-muted">{toast.description}</p> : null}
        {toast.action ? (
          <Link
            to={toast.action.to}
            onClick={() => onDismiss(toast.id)}
            className="mt-1 inline-block font-medium text-accent-text underline underline-offset-2"
          >
            {toast.action.label}
          </Link>
        ) : null}
      </div>
      <button
        type="button"
        aria-label="Dismiss notification"
        onClick={() => onDismiss(toast.id)}
        className="shrink-0 rounded p-0.5 text-fg-muted hover:bg-surface-muted hover:text-fg"
      >
        <X aria-hidden="true" className="size-4" />
      </button>
    </div>
  );
}

/**
 * Provides `toast()` and renders two persistent live regions: polite
 * (`role="status"`) for normal toasts and assertive (`role="alert"`) for errors.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counter = useRef(0);

  const dismiss = useCallback((id: string) => {
    setToasts((current) => current.filter((item) => item.id !== id));
  }, []);

  const toast = useCallback((input: ToastInput) => {
    counter.current += 1;
    const id = input.id ?? `toast-${counter.current}`;
    const next: Toast = { ...input, id };
    setToasts((current) => [...current.filter((item) => item.id !== id), next].slice(-MAX_TOASTS));
    return id;
  }, []);

  const value = useMemo<ToastValue>(() => ({ toast, dismiss }), [toast, dismiss]);
  const errors = toasts.filter((item) => item.tone === "error");
  const others = toasts.filter((item) => item.tone !== "error");

  return (
    <ToastContext value={value}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-end gap-2 p-4 sm:left-auto sm:w-96">
        <div role="alert" aria-live="assertive" className="flex w-full flex-col gap-2">
          {errors.map((item) => (
            <ToastItem key={item.id} toast={item} onDismiss={dismiss} />
          ))}
        </div>
        <div role="status" aria-live="polite" className="flex w-full flex-col gap-2">
          {others.map((item) => (
            <ToastItem key={item.id} toast={item} onDismiss={dismiss} />
          ))}
        </div>
      </div>
    </ToastContext>
  );
}
