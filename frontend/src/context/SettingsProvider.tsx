import { useCallback, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";
import { readStorage, removeStorage, STORAGE_KEYS, writeStorage } from "../lib/storage";
import { isThemePreference, SettingsContext, type SettingsValue, type ThemePreference } from "./settings";

const DARK_QUERY = "(prefers-color-scheme: dark)";

function darkQuery(): MediaQueryList | null {
  return typeof window.matchMedia === "function" ? window.matchMedia(DARK_QUERY) : null;
}

/** Subscribes to OS color-scheme changes (used while the preference is "system"). */
function subscribeToScheme(onChange: () => void): () => void {
  const query = darkQuery();
  if (!query) return () => undefined;
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

const systemPrefersDark = (): boolean => darkQuery()?.matches ?? false;

/** Applies the resolved theme to <html> (class used by the `dark:` variant and CSS tokens). */
function applyTheme(dark: boolean): void {
  const root = document.documentElement;
  root.classList.toggle("dark", dark);
  root.style.colorScheme = dark ? "dark" : "light";
}

/** Holds the API key (localStorage `pes.apiKey`) and theme (`pes.theme`, default "system"). */
export function SettingsProvider({ children }: { children: ReactNode }) {
  const [apiKey, setApiKeyState] = useState(() =>
    readStorage(STORAGE_KEYS.apiKey, "", (value): value is string => typeof value === "string"),
  );
  const [theme, setThemeState] = useState<ThemePreference>(() =>
    readStorage<ThemePreference>(STORAGE_KEYS.theme, "system", isThemePreference),
  );
  const prefersDark = useSyncExternalStore(subscribeToScheme, systemPrefersDark, () => false);
  const resolvedTheme = theme === "system" ? (prefersDark ? "dark" : "light") : theme;

  useEffect(() => {
    applyTheme(resolvedTheme === "dark");
  }, [resolvedTheme]);

  const setApiKey = useCallback((key: string) => {
    const trimmed = key.trim();
    writeStorage(STORAGE_KEYS.apiKey, trimmed);
    setApiKeyState(trimmed);
  }, []);

  const clearApiKey = useCallback(() => {
    removeStorage(STORAGE_KEYS.apiKey);
    setApiKeyState("");
  }, []);

  const setTheme = useCallback((next: ThemePreference) => {
    writeStorage(STORAGE_KEYS.theme, next);
    setThemeState(next);
  }, []);

  const value = useMemo<SettingsValue>(
    () => ({ apiKey, setApiKey, clearApiKey, theme, setTheme, resolvedTheme }),
    [apiKey, setApiKey, clearApiKey, theme, setTheme, resolvedTheme],
  );

  return <SettingsContext value={value}>{children}</SettingsContext>;
}
