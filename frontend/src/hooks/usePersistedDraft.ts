import { useEffect, useRef } from "react";
import { writeStorage } from "../lib/storage";

/**
 * Saves `value` to localStorage `delayMs` after it last changed, and saves a
 * pending change at once when the component unmounts (in-app navigation) or
 * the page is hidden (reload, tab close, mobile app switch), so the last
 * keystrokes are never lost.
 *
 * Pass a memoized value: a new object on every render would restart the delay.
 */
export function usePersistedDraft(key: string, value: unknown, delayMs = 400): void {
  const latest = useRef<{ value: unknown; pending: boolean }>({ value, pending: false });

  useEffect(() => {
    latest.current = { value, pending: true };
    const timer = window.setTimeout(() => {
      writeStorage(key, value);
      latest.current.pending = false;
    }, delayMs);
    return () => window.clearTimeout(timer);
  }, [key, value, delayMs]);

  useEffect(() => {
    const flush = () => {
      if (!latest.current.pending) return;
      writeStorage(key, latest.current.value);
      latest.current.pending = false;
    };
    window.addEventListener("pagehide", flush);
    return () => {
      window.removeEventListener("pagehide", flush);
      flush();
    };
  }, [key]);
}
