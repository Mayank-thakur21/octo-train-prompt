import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "../../lib/cn";
import { IconButton } from "./IconButton";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), ' +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"]), summary';

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  /** `center` = modal dialog, `drawer` = panel sliding in from the right, `left` = navigation drawer. */
  variant?: "center" | "drawer" | "left";
  /**
   * Whether a click on the backdrop closes the dialog (default true). Forms
   * pass false once they hold unsaved input, so a stray tap outside the panel
   * cannot discard it; Escape, the close button and Cancel still close.
   */
  closeOnBackdrop?: boolean;
  className?: string;
}

const SIZES: Record<NonNullable<DialogProps["size"]>, string> = {
  sm: "max-w-md",
  md: "max-w-lg",
  lg: "max-w-2xl",
  xl: "max-w-4xl",
};

/** Elements inside `root` that can receive keyboard focus, in tab order. */
function focusableIn(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (element) => !element.hasAttribute("disabled") && element.getAttribute("aria-hidden") !== "true",
  );
}

/**
 * Accessible modal: rendered in a portal with `role="dialog"` and `aria-modal`,
 * traps focus, closes on Escape or backdrop click (unless `closeOnBackdrop` is
 * false), locks page scroll and restores focus to the opener when it closes.
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
  variant = "center",
  closeOnBackdrop = true,
  className,
}: DialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return undefined;
    const panel = panelRef.current;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    if (panel) {
      const preferred = panel.querySelector<HTMLElement>("[data-autofocus]");
      const first = focusableIn(panel).find((element) => !element.dataset.dialogClose);
      (preferred ?? first ?? panel).focus();
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !panel) return;
      const items = focusableIn(panel);
      if (items.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const firstItem = items[0];
      const lastItem = items[items.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === firstItem || active === panel)) {
        event.preventDefault();
        lastItem?.focus();
      } else if (!event.shiftKey && active === lastItem) {
        event.preventDefault();
        firstItem?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.body.style.overflow = previousOverflow;
      if (previous?.isConnected) previous.focus();
    };
  }, [open]);

  if (!open) return null;

  const placement =
    variant === "center"
      ? "items-end justify-center p-0 sm:items-center sm:p-4"
      : variant === "drawer"
        ? "items-stretch justify-end"
        : "items-stretch justify-start";
  const panelShape =
    variant === "center"
      ? cn("w-full max-h-[92dvh] rounded-t-xl sm:rounded-xl", SIZES[size])
      : cn("h-full w-full max-w-[min(100vw,42rem)]", variant === "left" && "max-w-[18rem]");

  return createPortal(
    <div className={cn("fixed inset-0 z-50 flex", placement)}>
      <div
        className="absolute inset-0 bg-backdrop"
        aria-hidden="true"
        data-testid="dialog-backdrop"
        onClick={() => {
          if (closeOnBackdrop) onCloseRef.current();
        }}
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={cn(
          "relative flex flex-col overflow-hidden border border-line bg-surface text-fg shadow-xl",
          panelShape,
          className,
        )}
      >
        <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0">
            <h2 id={titleId} className="text-base font-semibold">
              {title}
            </h2>
            {description ? (
              <p id={descriptionId} className="mt-0.5 text-sm text-fg-muted">
                {description}
              </p>
            ) : null}
          </div>
          <IconButton
            label="Close dialog"
            icon={<X aria-hidden="true" className="size-4" />}
            size="sm"
            data-dialog-close="true"
            onClick={() => onCloseRef.current()}
          />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">{children}</div>
        {footer ? (
          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-4 py-3">{footer}</div>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}
