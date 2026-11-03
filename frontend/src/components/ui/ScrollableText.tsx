import { useScrollableRegion } from "../../hooks/useScrollableRegion";
import { cn } from "../../lib/cn";

export interface ScrollableTextProps {
  /** What the text is, e.g. "User prompt"; names the region once it scrolls. */
  label: string;
  text: string;
  className?: string;
}

/**
 * Preformatted text in a height-limited box. Long unbroken words wrap instead
 * of scrolling sideways; when the text is taller than the box, the box becomes
 * a focusable region so it can be scrolled from the keyboard.
 */
export function ScrollableText({ label, text, className }: ScrollableTextProps) {
  const [ref, region] = useScrollableRegion<HTMLPreElement>(label, text);
  return (
    <pre
      ref={ref}
      {...region}
      className={cn(
        "overflow-auto rounded-md border border-line bg-surface-muted p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap [overflow-wrap:anywhere]",
        className,
      )}
    >
      {text}
    </pre>
  );
}
