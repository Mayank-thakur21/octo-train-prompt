/** Shared class recipes for form controls and buttons (kept out of component files for Fast Refresh). */
import { cn } from "../../lib/cn";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

const BUTTON_BASE =
  "inline-flex items-center justify-center gap-2 rounded-md font-medium whitespace-nowrap transition-colors " +
  "disabled:cursor-not-allowed disabled:opacity-55 select-none";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent text-accent-fg hover:bg-accent-hover border border-transparent",
  secondary: "bg-surface text-fg border border-line-strong hover:bg-surface-muted",
  ghost: "bg-transparent text-fg border border-transparent hover:bg-surface-muted",
  danger: "bg-surface text-danger border border-danger hover:bg-danger-soft",
};

const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: "h-8 px-2.5 text-sm",
  md: "h-10 px-4 text-sm",
};

/** Classes for a button-looking element (also used for links styled as buttons). */
export function buttonClasses(variant: ButtonVariant = "secondary", size: ButtonSize = "md", className?: string): string {
  return cn(BUTTON_BASE, BUTTON_VARIANTS[variant], BUTTON_SIZES[size], className);
}

/** Square icon-only button: same look as `buttonClasses` without horizontal padding. */
export function iconButtonClasses(variant: ButtonVariant = "ghost", size: ButtonSize = "md", className?: string): string {
  return cn(BUTTON_BASE, BUTTON_VARIANTS[variant], size === "sm" ? "size-8" : "size-10", "shrink-0", className);
}

export interface InputClassOptions {
  /** Monospace text for prompt/code editing. */
  mono?: boolean;
  /** Padding utilities (replaces the default `px-3 py-2`). */
  padding?: string;
}

/**
 * Classes for text inputs, selects and textareas. Padding and font size are
 * options rather than overrides so no two utilities fight over one property.
 */
export function inputClasses(invalid = false, className?: string, options: InputClassOptions = {}): string {
  return cn(
    "w-full rounded-md border bg-surface text-fg placeholder:text-fg-muted",
    "disabled:cursor-not-allowed disabled:opacity-60",
    options.padding ?? "px-3 py-2",
    options.mono ? "font-mono text-[13px]" : "text-sm",
    invalid ? "border-danger" : "border-line-strong",
    className,
  );
}

/** Label typography shared by every field. */
export const LABEL_CLASSES = "min-w-0 text-sm font-medium text-fg [overflow-wrap:anywhere]";

/** Small helper/hint text under a field. */
export const HINT_CLASSES = "text-xs text-fg-muted";

/** Inline error text under a field. */
export const ERROR_TEXT_CLASSES = "text-xs font-medium text-danger";

/** Joins the ids of present description elements for `aria-describedby`. */
export function describedBy(...ids: Array<string | false | null | undefined>): string | undefined {
  const value = ids.filter(Boolean).join(" ");
  return value || undefined;
}
