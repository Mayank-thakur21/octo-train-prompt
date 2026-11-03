import { describe, expect, it } from "vitest";
import { assertionToDraft, changeDraftType, draftToAssertion, newAssertionDraft, summarizeAssertions } from "./assertions";

describe("assertion drafts", () => {
  it("round-trips every assertion type", () => {
    const assertions = [
      { type: "contains", value: "a", case_sensitive: false },
      { type: "not_contains", value: "b", case_sensitive: true },
      { type: "equals", value: "c", case_sensitive: true, trim: false },
      { type: "starts_with", value: "d", case_sensitive: false, trim: true },
      { type: "regex", pattern: "^x", flags: "im" },
      { type: "max_chars", value: 500 },
      { type: "min_chars", value: 0 },
      { type: "json_valid" },
      { type: "json_schema", schema: { type: "object", required: ["a"] } },
      { type: "llm_judge", rubric: "Polite", threshold: 3, judge_model: "demo-concise" },
    ] as const;
    for (const assertion of assertions) {
      expect(draftToAssertion(assertionToDraft(assertion))).toEqual({ ok: true, assertion });
    }
  });

  it("validates required fields and limits", () => {
    expect(draftToAssertion(newAssertionDraft("contains"))).toEqual({ ok: false, error: "Enter the expected text." });
    expect(draftToAssertion({ ...newAssertionDraft("regex"), pattern: "" }).ok).toBe(false);
    expect(draftToAssertion({ ...newAssertionDraft("max_chars"), chars: "-1" }).ok).toBe(false);
    expect(draftToAssertion({ ...newAssertionDraft("json_schema"), schemaText: "{oops" })).toEqual({
      ok: false,
      error: "The schema is not valid JSON.",
    });
    expect(draftToAssertion({ ...newAssertionDraft("json_schema"), schemaText: "[1]" })).toEqual({
      ok: false,
      error: "The schema must be a JSON object.",
    });
    expect(draftToAssertion({ ...newAssertionDraft("llm_judge"), rubric: "  " }).ok).toBe(false);
  });

  it("resets case options to the type defaults when switching type", () => {
    const draft = { ...newAssertionDraft("contains"), value: "kept" };
    const switched = changeDraftType(draft, "equals");
    expect(switched).toMatchObject({ type: "equals", value: "kept", caseSensitive: true, trim: true });
    expect(changeDraftType(switched, "not_contains").caseSensitive).toBe(false);
  });

  it("normalizes regex flags to the supported subset in order", () => {
    expect(draftToAssertion({ ...newAssertionDraft("regex"), pattern: "a", flags: "smx" })).toEqual({
      ok: true,
      assertion: { type: "regex", pattern: "a", flags: "ms" },
    });
  });

  it("summarizes assertion lists", () => {
    expect(summarizeAssertions([])).toBe("No assertions");
    expect(summarizeAssertions([{ type: "json_valid" }, { type: "llm_judge", rubric: "x", threshold: 4, judge_model: null }])).toBe(
      "Valid JSON, LLM judge",
    );
  });
});
