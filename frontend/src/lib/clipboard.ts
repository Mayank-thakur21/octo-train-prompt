/**
 * Clipboard writing that also works on plain-HTTP deployments.
 *
 * `navigator.clipboard` only exists in secure contexts (HTTPS or localhost),
 * so a self-hosted server opened as http://server:3000 has none. There the
 * legacy path copies a selected, off-screen textarea with
 * `document.execCommand("copy")`, which browsers still allow during a click.
 */

/** Copies with the deprecated selection API; returns whether the browser reported success. */
function copyWithSelection(text: string): boolean {
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.setAttribute("aria-hidden", "true");
  area.style.position = "fixed";
  area.style.top = "0";
  area.style.left = "-9999px";
  area.style.opacity = "0";
  const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  document.body.append(area);
  try {
    area.focus({ preventScroll: true });
    area.select();
    area.setSelectionRange(0, text.length);
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    area.remove();
    previous?.focus();
  }
}

/** Writes `text` to the clipboard; resolves to false when every method failed. */
export async function copyText(text: string): Promise<boolean> {
  if (typeof navigator.clipboard?.writeText === "function") {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Permission denied or not focused: try the legacy path below.
    }
  }
  return copyWithSelection(text);
}
