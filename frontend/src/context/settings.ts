/** Settings context: stored API key and theme preference. */
import { createContext, useContext } from "react";

export type ThemePreference = "dark" | "light" | "system";
export type ResolvedTheme = "dark" | "light";

export const THEME_PREFERENCES: readonly ThemePreference[] = ["dark", "light", "system"];

export function isThemePreference(value: unknown): value is ThemePreference {
  return value === "dark" || value === "light" || value === "system";
}

export interface SettingsValue {
  /** API key sent as `X-API-Key` ("" when none). */
  apiKey: string;
  setApiKey: (key: string) => void;
  clearApiKey: () => void;
  theme: ThemePreference;
  setTheme: (theme: ThemePreference) => void;
  /** Theme actually applied (system preference resolved). */
  resolvedTheme: ResolvedTheme;
}

export const SettingsContext = createContext<SettingsValue | null>(null);

/** Access the settings; must be used inside `SettingsProvider`. */
export function useSettings(): SettingsValue {
  const value = useContext(SettingsContext);
  if (!value) throw new Error("useSettings must be used inside SettingsProvider.");
  return value;
}
