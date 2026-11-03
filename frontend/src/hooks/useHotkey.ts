import { useEffect, useEffectEvent } from "react";

export interface HotkeyOptions {
  /** `KeyboardEvent.key` to match, e.g. "Enter". */
  key: string;
  /** Require Ctrl (Windows/Linux) or Cmd (macOS). */
  mod?: boolean;
  enabled?: boolean;
}

/** Registers a window-level shortcut such as Ctrl/Cmd+Enter. The latest handler is always used. */
export function useHotkey({ key, mod = false, enabled = true }: HotkeyOptions, handler: (event: KeyboardEvent) => void): void {
  const onHotkey = useEffectEvent(handler);
  useEffect(() => {
    if (!enabled) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.isComposing || event.key !== key) return;
      if (mod && !(event.ctrlKey || event.metaKey)) return;
      event.preventDefault();
      onHotkey(event);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [key, mod, enabled]);
}
