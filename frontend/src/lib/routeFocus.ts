/**
 * Moves keyboard focus to the page heading after client-side navigation
 * (contract section 8.4). The layout calls `focusPageHeading()` when the path
 * changes; if the page is still loading, the heading claims the pending focus
 * when it mounts.
 */
let pendingFocus = false;

/** Focuses the current page's `<h1>`, or remembers to do so once it renders. */
export function focusPageHeading(): void {
  const heading = document.querySelector<HTMLElement>("#main h1");
  if (heading) {
    heading.focus({ preventScroll: false });
    pendingFocus = false;
  } else {
    pendingFocus = true;
  }
}

/** Returns true (once) when a heading should take focus on mount. */
export function consumePendingHeadingFocus(): boolean {
  const pending = pendingFocus;
  pendingFocus = false;
  return pending;
}
