import type { HTMLAttributes } from "react";
import { useScrollableRegion } from "../../hooks/useScrollableRegion";
import { cn } from "../../lib/cn";

export interface HorizontalScrollProps extends HTMLAttributes<HTMLDivElement> {
  /**
   * Accessible name for content without focusable elements (such as a diff).
   * When given and the content is wider than the box, the box becomes a
   * focusable, labelled region, so keyboard users can scroll it with the
   * arrow keys in every browser (axe `scrollable-region-focusable`).
   */
  label?: string;
}

/**
 * Scroll container for wide tables and grids on narrow screens.
 *
 * `relative` makes it the containing block of absolutely positioned descendants such as
 * `sr-only` captions and labels; without it those elements are positioned against the page and
 * widen it, which brings back the page-level horizontal scroll this wrapper exists to prevent.
 */
export function HorizontalScroll({ className, children, label, ...rest }: HorizontalScrollProps) {
  const [ref, region] = useScrollableRegion<HTMLDivElement>(label);
  return (
    <div
      {...rest}
      ref={ref}
      tabIndex={region.tabIndex ?? rest.tabIndex}
      role={region.role ?? rest.role}
      aria-label={region["aria-label"] ?? rest["aria-label"]}
      className={cn("relative overflow-x-auto", className)}
    >
      {children}
    </div>
  );
}
