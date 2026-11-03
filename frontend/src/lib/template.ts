/**
 * Template grammar (contract section 4), mirrored from the backend so the
 * Playground can build its variable form and previews locally.
 *
 *   {{name}}            placeholder (ASCII letter or "_" first, max 64 chars)
 *   {{name|default}}    placeholder with a default (trimmed, no newlines)
 *   \{{                 escape: renders a literal "{{"
 *
 * The grammar is defined by this regex (section 4.1):
 *
 *   /\\\{\{|\{\{\s*([A-Za-z_][A-Za-z0-9_]{0,63})\s*(?:\|([^\n]*?))?\}\}/g
 *
 * Running it directly takes quadratic time (every "{{a|" without a closing
 * "}}" on its line rescans to the end of the line), which froze the tab on
 * long prompts. `scan` finds exactly the same matches in linear time, like
 * the backend: a sticky regex matches the bounded head, and the end of a
 * default comes from cached indexOf lookups whose positions only move forward.
 */
import type { VariableInfo } from "../api/types";

/** "{{", optional whitespace, the name, optional whitespace, then "}}" or "|" (a default follows). */
const HEAD = /\{\{\s*([A-Za-z_][A-Za-z0-9_]{0,63})\s*(\}\}|\|)/y;

/** One grammar match: an escape (`name === null`) or a placeholder; `text.slice(start, end)` is the match. */
export interface Token {
  start: number;
  end: number;
  name: string | null;
  /** Raw (untrimmed) default, or null when the placeholder declares none. */
  default: string | null;
}

/** `text.indexOf(needle, pos)` with a cache: linear in total while `pos` does not decrease. */
function forwardFinder(text: string, needle: string): (pos: number) => number {
  let searchedFrom = -1;
  let found = -1;
  return (pos) => {
    // The cached answer still holds unless `pos` moved before the old start or past the hit.
    const cached = searchedFrom >= 0 && pos >= searchedFrom && (found === -1 || found >= pos);
    if (!cached) {
      searchedFrom = pos;
      found = text.indexOf(needle, pos);
    }
    return found;
  };
}

/** The grammar's matches, left to right, exactly as the section 4.1 regex finds them. */
export function scan(text: string): Token[] {
  const tokens: Token[] = [];
  const findClose = forwardFinder(text, "}}");
  const findNewline = forwardFinder(text, "\n");
  let pos = 0;
  for (;;) {
    const brace = text.indexOf("{{", pos);
    if (brace < 0) return tokens;
    // "\{{" is the leftmost possible match when its backslash is still unscanned.
    if (brace - 1 >= pos && text[brace - 1] === "\\") {
      tokens.push({ start: brace - 1, end: brace + 2, name: null, default: null });
      pos = brace + 2;
      continue;
    }
    if (findClose(brace + 2) < 0) {
      // Every placeholder ends with "}}", so only escapes can follow.
      for (let start = text.indexOf("\\{{", pos); start >= 0; start = text.indexOf("\\{{", start + 3)) {
        tokens.push({ start, end: start + 3, name: null, default: null });
      }
      return tokens;
    }
    HEAD.lastIndex = brace;
    const head = HEAD.exec(text);
    const name = head?.[1];
    if (!head || name === undefined) {
      pos = brace + 1;
      continue;
    }
    if (head[2] === "}}") {
      tokens.push({ start: brace, end: HEAD.lastIndex, name, default: null });
      pos = HEAD.lastIndex;
      continue;
    }
    // A default runs from after "|" to the first "}}" and must not contain a newline.
    const defaultStart = HEAD.lastIndex;
    const close = findClose(defaultStart);
    const newline = findNewline(defaultStart);
    if (close < 0 || (newline >= 0 && newline < close)) {
      pos = brace + 1;
      continue;
    }
    tokens.push({ start: brace, end: close + 2, name, default: text.slice(defaultStart, close) });
    pos = close + 2;
  }
}

/** Variable name rule shared by placeholders and case variable keys. */
export const VARIABLE_NAME = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;

interface Placeholder {
  name: string;
  /** Trimmed default, or null when the occurrence declares none. */
  default: string | null;
}

/** Placeholders of one text in order (escapes are skipped). */
function placeholders(text: string): Placeholder[] {
  const found: Placeholder[] = [];
  for (const token of scan(text)) {
    if (token.name === null) continue;
    found.push({ name: token.name, default: token.default === null ? null : token.default.trim() });
  }
  return found;
}

/**
 * Unique variables of system then prompt, in order of first appearance.
 * `default` is the first default declared for a name anywhere; `required`
 * means no occurrence declares a default.
 */
export function extractVariables(system: string | null | undefined, prompt: string): VariableInfo[] {
  const order: string[] = [];
  const defaults = new Map<string, string | null>();
  for (const item of [...placeholders(system ?? ""), ...placeholders(prompt)]) {
    if (!defaults.has(item.name)) {
      order.push(item.name);
      defaults.set(item.name, item.default);
    } else if (defaults.get(item.name) === null && item.default !== null) {
      defaults.set(item.name, item.default);
    }
  }
  return order.map((name) => {
    const value = defaults.get(name) ?? null;
    return { name, default: value, required: value === null };
  });
}

/**
 * Union of the variables of several templates (Compare variants), in order of
 * first appearance.
 *
 * The server renders each variant on its own, with that variant's defaults, and
 * empty fields are not sent. So a variable is required as soon as one template
 * that uses it declares no default; it is optional only when every template
 * can fall back on its own default, and then `default` is the first one.
 */
export function unionVariables(templates: ReadonlyArray<{ system: string | null; prompt: string }>): VariableInfo[] {
  const merged = new Map<string, VariableInfo>();
  for (const template of templates) {
    for (const info of extractVariables(template.system, template.prompt)) {
      const existing = merged.get(info.name);
      if (!existing) merged.set(info.name, info);
      else if (info.required && !existing.required) merged.set(info.name, { name: info.name, default: null, required: true });
    }
  }
  return [...merged.values()];
}

export interface RenderOutput {
  system: string | null;
  prompt: string;
  /** Names without a value or default, sorted alphabetically. */
  missing: string[];
}

/**
 * Renders system and prompt with the same variables (lenient: missing
 * placeholders are kept verbatim and listed in `missing`). Values are
 * inserted as-is and never re-scanned.
 */
export function renderTemplate(
  system: string | null | undefined,
  prompt: string,
  variables: Record<string, string>,
): RenderOutput {
  const firstDefaults = new Map<string, string>();
  for (const info of extractVariables(system, prompt)) {
    if (info.default !== null) firstDefaults.set(info.name, info.default);
  }
  const missing = new Set<string>();
  const renderOne = (text: string): string => {
    const parts: string[] = [];
    let pos = 0;
    for (const token of scan(text)) {
      parts.push(text.slice(pos, token.start));
      pos = token.end;
      const name = token.name;
      if (name === null) {
        parts.push("{{");
      } else if (Object.hasOwn(variables, name)) {
        parts.push(variables[name] ?? "");
      } else if (token.default !== null) {
        parts.push(token.default.trim());
      } else {
        const declared = firstDefaults.get(name);
        if (declared === undefined) {
          missing.add(name);
          parts.push(text.slice(token.start, token.end));
        } else {
          parts.push(declared);
        }
      }
    }
    parts.push(text.slice(pos));
    return parts.join("");
  };
  return {
    system: system === null || system === undefined ? null : renderOne(system),
    prompt: renderOne(prompt),
    missing: [...missing].sort(),
  };
}

/** Keeps only non-empty values for the given variable names (empty fields are never sent, section 4.3). */
export function nonEmptyValues(values: Record<string, string>, names: readonly string[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (const name of names) {
    const value = values[name];
    if (value !== undefined && value !== "") result[name] = value;
  }
  return result;
}
