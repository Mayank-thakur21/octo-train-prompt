import { useEffect, useRef, useState, type RefObject } from "react";

/** Attributes that make a scroll box reachable from the keyboard once its content overflows. */
export interface ScrollableRegionAttributes {
  tabIndex: number | undefined;
  role: "region" | undefined;
  "aria-label": string | undefined;
}

/**
 * Keyboard access for a scroll box without focusable content (a diff, a long
 * template). While its content overflows the box, the box becomes a focusable,
 * labelled region so arrow keys scroll it in every browser (axe
 * `scrollable-region-focusable`); while everything fits it stays out of the
 * tab order. Pass `label` undefined to opt out. `content` (for example the
 * displayed text) triggers a new measurement when it changes, for boxes whose
 * own size stays fixed while their content grows.
 */
export function useScrollableRegion<T extends HTMLElement>(
  label: string | undefined,
  content?: unknown,
): [RefObject<T | null>, ScrollableRegionAttributes] {
  const ref = useRef<T>(null);
  const [overflowing, setOverflowing] = useState(false);

  useEffect(() => {
    const element = ref.current;
    if (!element || label === undefined || typeof ResizeObserver === "undefined") return undefined;
    // The observer reports once when observing starts and again whenever the box or its
    // content changes size (viewport rotation, longer text).
    const observer = new ResizeObserver(() =>
      setOverflowing(element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1),
    );
    observer.observe(element);
    for (const child of Array.from(element.children)) observer.observe(child);
    return () => observer.disconnect();
  }, [label, content]);

  const scrollable = label !== undefined && overflowing;
  return [
    ref,
    {
      tabIndex: scrollable ? 0 : undefined,
      role: scrollable ? "region" : undefined,
      "aria-label": scrollable ? `${label}, scrollable` : undefined,
    },
  ];
}
