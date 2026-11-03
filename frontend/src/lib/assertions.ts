/**
 * Assertion editing model. The editor works on a flat draft holding the
 * fields of every assertion type, so switching types never loses typed text;
 * `draftToAssertion` validates and produces the wire shape (section 2.4).
 */
import type { Assertion, AssertionType } from "../api/types";

export const ASSERTION_TYPES: ReadonlyArray<{ type: AssertionType; label: string }> = [
  { type: "contains", label: "Contains" },
  { type: "not_contains", label: "Does not contain" },
  { type: "equals", label: "Equals" },
  { type: "starts_with", label: "Starts with" },
  { type: "regex", label: "Matches regex" },
  { type: "max_chars", label: "Max characters" },
  { type: "min_chars", label: "Min characters" },
  { type: "json_valid", label: "Valid JSON" },
  { type: "json_schema", label: "Matches JSON schema" },
  { type: "llm_judge", label: "LLM judge" },
];

export function assertionLabel(type: AssertionType): string {
  return ASSERTION_TYPES.find((item) => item.type === type)?.label ?? type;
}

export interface AssertionDraft {
  /** Stable React key. */
  key: string;
  type: AssertionType;
  value: string;
  caseSensitive: boolean;
  trim: boolean;
  pattern: string;
  flags: string;
  chars: string;
  schemaText: string;
  rubric: string;
  threshold: number;
  judgeModel: string | null;
}

let draftCounter = 0;
function nextKey(): string {
  draftCounter += 1;
  return `assertion-${draftCounter}`;
}

/** Contract defaults: contains/not_contains are case-insensitive, equals/starts_with case-sensitive and trimmed. */
export function defaultCaseSensitive(type: AssertionType): boolean {
  return type === "equals" || type === "starts_with";
}

export function newAssertionDraft(type: AssertionType = "contains"): AssertionDraft {
  return {
    key: nextKey(),
    type,
    value: "",
    caseSensitive: defaultCaseSensitive(type),
    trim: true,
    pattern: "",
    flags: "",
    chars: type === "min_chars" ? "1" : "500",
    schemaText: '{\n  "type": "object"\n}',
    rubric: "",
    threshold: 4,
    judgeModel: null,
  };
}

/** Changes the type, resetting the case/trim options to that type's defaults. */
export function changeDraftType(draft: AssertionDraft, type: AssertionType): AssertionDraft {
  return { ...draft, type, caseSensitive: defaultCaseSensitive(type), trim: true };
}

export function assertionToDraft(assertion: Assertion): AssertionDraft {
  const draft = newAssertionDraft(assertion.type);
  switch (assertion.type) {
    case "contains":
    case "not_contains":
      return { ...draft, value: assertion.value, caseSensitive: assertion.case_sensitive };
    case "equals":
    case "starts_with":
      return { ...draft, value: assertion.value, caseSensitive: assertion.case_sensitive, trim: assertion.trim };
    case "regex":
      return { ...draft, pattern: assertion.pattern, flags: assertion.flags };
    case "max_chars":
    case "min_chars":
      return { ...draft, chars: String(assertion.value) };
    case "json_valid":
      return draft;
    case "json_schema":
      return { ...draft, schemaText: JSON.stringify(assertion.schema, null, 2) };
    case "llm_judge":
      return { ...draft, rubric: assertion.rubric, threshold: assertion.threshold, judgeModel: assertion.judge_model };
  }
}

export type DraftResult = { ok: true; assertion: Assertion } | { ok: false; error: string };

/** Validates a draft against the contract limits and converts it to an `Assertion`. */
export function draftToAssertion(draft: AssertionDraft): DraftResult {
  switch (draft.type) {
    case "contains":
    case "not_contains":
    case "equals":
    case "starts_with": {
      if (draft.value.length < 1) return { ok: false, error: "Enter the expected text." };
      if (draft.value.length > 10000) return { ok: false, error: "The value can be at most 10,000 characters." };
      if (draft.type === "contains" || draft.type === "not_contains") {
        return { ok: true, assertion: { type: draft.type, value: draft.value, case_sensitive: draft.caseSensitive } };
      }
      return {
        ok: true,
        assertion: { type: draft.type, value: draft.value, case_sensitive: draft.caseSensitive, trim: draft.trim },
      };
    }
    case "regex": {
      if (draft.pattern.length < 1) return { ok: false, error: "Enter a regular expression." };
      if (draft.pattern.length > 500) return { ok: false, error: "The pattern can be at most 500 characters." };
      const flags = ["i", "m", "s"].filter((flag) => draft.flags.includes(flag)).join("");
      return { ok: true, assertion: { type: "regex", pattern: draft.pattern, flags } };
    }
    case "max_chars":
    case "min_chars": {
      const trimmed = draft.chars.trim();
      if (!/^\d+$/.test(trimmed)) return { ok: false, error: "Enter a whole number of characters (0 or more)." };
      return { ok: true, assertion: { type: draft.type, value: Number.parseInt(trimmed, 10) } };
    }
    case "json_valid":
      return { ok: true, assertion: { type: "json_valid" } };
    case "json_schema": {
      let parsed: unknown;
      try {
        parsed = JSON.parse(draft.schemaText);
      } catch {
        return { ok: false, error: "The schema is not valid JSON." };
      }
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        return { ok: false, error: "The schema must be a JSON object." };
      }
      return { ok: true, assertion: { type: "json_schema", schema: parsed as Record<string, unknown> } };
    }
    case "llm_judge": {
      if (draft.rubric.trim().length < 1) return { ok: false, error: "Describe what a good answer looks like." };
      if (draft.rubric.length > 4000) return { ok: false, error: "The rubric can be at most 4,000 characters." };
      const threshold = Math.min(5, Math.max(1, Math.round(draft.threshold)));
      return {
        ok: true,
        assertion: { type: "llm_judge", rubric: draft.rubric, threshold, judge_model: draft.judgeModel },
      };
    }
  }
}

/** Short human summary of an assertion list, e.g. "Contains, LLM judge". */
export function summarizeAssertions(assertions: readonly Assertion[]): string {
  if (assertions.length === 0) return "No assertions";
  return assertions.map((assertion) => assertionLabel(assertion.type)).join(", ");
}
