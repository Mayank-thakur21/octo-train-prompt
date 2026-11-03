/**
 * Safe wrappers around `localStorage`.
 * Values are stored as JSON. Every access is guarded because storage can be
 * unavailable (private mode, blocked cookies) or hold corrupted data.
 */

/** localStorage keys used by the app (part of the documented behaviour). */
export const STORAGE_KEYS = {
  apiKey: "pes.apiKey",
  theme: "pes.theme",
  playgroundDraft: "pes.playground.draft",
  compareDraft: "pes.compare.draft",
} as const;

/**
 * Reads and JSON-decodes a value. Returns `fallback` when the key is missing,
 * unreadable, not valid JSON, or rejected by the optional `validate` guard.
 */
export function readStorage<T>(key: string, fallback: T, validate?: (value: unknown) => value is T): T {
  try {
    const raw = window.localStorage.getItem(key);
    if (raw === null) return fallback;
    const parsed: unknown = JSON.parse(raw);
    if (validate && !validate(parsed)) return fallback;
    return parsed as T;
  } catch {
    return fallback;
  }
}

/** JSON-encodes and stores a value. Returns false when storage is unavailable or full. */
export function writeStorage(key: string, value: unknown): boolean {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

/** Removes a key, ignoring storage errors. */
export function removeStorage(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Storage unavailable: nothing to remove.
  }
}

/** Type guard for plain JSON objects. */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Type guard for `Record<string, string>`. */
export function isStringRecord(value: unknown): value is Record<string, string> {
  return isRecord(value) && Object.values(value).every((v) => typeof v === "string");
}
