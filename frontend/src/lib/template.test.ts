import { describe, expect, it } from "vitest";
import { extractVariables, nonEmptyValues, renderTemplate, scan } from "./template";

type Extracted = Array<[string, string | null, boolean]>;

/** Contract section 4.4 vectors: system, prompt, variables, rendered prompt (strict), extracted. */
const VECTORS: Array<{
  id: number;
  system?: string;
  prompt: string;
  variables: Record<string, string>;
  rendered: string;
  extracted: Extracted;
  renderedSystem?: string;
}> = [
  { id: 1, prompt: "Hello {{name}}!", variables: { name: "Ada" }, rendered: "Hello Ada!", extracted: [["name", null, true]] },
  { id: 2, prompt: "Hi {{ name }}", variables: { name: "Ada" }, rendered: "Hi Ada", extracted: [["name", null, true]] },
  { id: 3, prompt: "{{tone|friendly}} tone", variables: {}, rendered: "friendly tone", extracted: [["tone", "friendly", false]] },
  {
    id: 4,
    prompt: "{{tone|friendly}} and {{tone}}",
    variables: {},
    rendered: "friendly and friendly",
    extracted: [["tone", "friendly", false]],
  },
  { id: 5, prompt: "{{tone}} and {{tone|calm}}", variables: {}, rendered: "calm and calm", extracted: [["tone", "calm", false]] },
  { id: 6, prompt: "{{a|x|y}}", variables: {}, rendered: "x|y", extracted: [["a", "x|y", false]] },
  { id: 7, prompt: "[{{a|}}]", variables: {}, rendered: "[]", extracted: [["a", "", false]] },
  {
    id: 8,
    prompt: "{{ name | Ada Lovelace }}",
    variables: {},
    rendered: "Ada Lovelace",
    extracted: [["name", "Ada Lovelace", false]],
  },
  { id: 9, prompt: "\\{{name}}", variables: {}, rendered: "{{name}}", extracted: [] },
  { id: 10, prompt: "{{not valid}} {{1abc}}", variables: {}, rendered: "{{not valid}} {{1abc}}", extracted: [] },
  { id: 11, prompt: '{"json": {"a": 1}}', variables: {}, rendered: '{"json": {"a": 1}}', extracted: [] },
  { id: 12, prompt: "{{{name}}}", variables: { name: "Ada" }, rendered: "{Ada}", extracted: [["name", null, true]] },
  { id: 13, prompt: "{{a}}", variables: { a: "{{b}}" }, rendered: "{{b}}", extracted: [["a", null, true]] },
  { id: 14, prompt: "[{{a|x}}]", variables: { a: "" }, rendered: "[]", extracted: [["a", "x", false]] },
  { id: 15, prompt: "{{a|line1\nline2}}", variables: {}, rendered: "{{a|line1\nline2}}", extracted: [] },
  { id: 16, prompt: `{{${"a".repeat(65)}}}`, variables: {}, rendered: `{{${"a".repeat(65)}}}`, extracted: [] },
  {
    id: 17,
    system: "{{b}}",
    prompt: "{{a}} {{b}}",
    variables: { a: "1", b: "2" },
    rendered: "1 2",
    renderedSystem: "2",
    extracted: [
      ["b", null, true],
      ["a", null, true],
    ],
  },
];

describe("extractVariables (section 4.4 vectors)", () => {
  it.each(VECTORS)("vector $id", ({ system, prompt, extracted }) => {
    const result = extractVariables(system ?? null, prompt).map((v) => [v.name, v.default, v.required]);
    expect(result).toEqual(extracted);
  });

  it("vector 18: extraction order and requiredness", () => {
    expect(extractVariables(null, "{{a}} {{b}} {{c|z}}")).toEqual([
      { name: "a", default: null, required: true },
      { name: "b", default: null, required: true },
      { name: "c", default: "z", required: false },
    ]);
  });
});

describe("renderTemplate (section 4.4 vectors)", () => {
  it.each(VECTORS)("vector $id", ({ system, prompt, variables, rendered, renderedSystem }) => {
    const result = renderTemplate(system ?? null, prompt, variables);
    expect(result.prompt).toBe(rendered);
    expect(result.missing).toEqual([]);
    if (renderedSystem !== undefined) expect(result.system).toBe(renderedSystem);
  });

  it("vector 18: lenient render keeps missing placeholders and lists them", () => {
    const result = renderTemplate(null, "{{a}} {{b}} {{c|z}}", { a: "1" });
    expect(result.prompt).toBe("1 {{b}} z");
    expect(result.missing).toEqual(["b"]);
  });

  it("sorts missing names and keeps the system null when absent", () => {
    const result = renderTemplate(null, "{{zeta}} {{alpha}}", {});
    expect(result.missing).toEqual(["alpha", "zeta"]);
    expect(result.system).toBeNull();
  });

  it("inserts values verbatim, even replacement-pattern characters", () => {
    expect(renderTemplate(null, "{{a}}", { a: "$& $1 $$" }).prompt).toBe("$& $1 $$");
  });
});

describe("nonEmptyValues", () => {
  it("drops empty values and names that are not used", () => {
    expect(nonEmptyValues({ a: "1", b: "", c: "3" }, ["a", "b"])).toEqual({ a: "1" });
  });
});

describe("scan (linear-time grammar)", () => {
  /** The section 4.1 regex, used only as a reference on short inputs. */
  const REFERENCE = /\\\{\{|\{\{\s*([A-Za-z_][A-Za-z0-9_]{0,63})\s*(?:\|([^\n]*?))?\}\}/g;
  const PIECES = ["{", "}", "{{", "}}", "|", "\\", "\n", " ", "a", "b", "_", "1", "\t", "{{a|", "{{ a ", "\\{{"];

  it("finds exactly the matches of the reference regex", () => {
    // Small deterministic PRNG (mulberry32) so failures are reproducible.
    let seed = 12345;
    const random = (): number => {
      seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    for (let round = 0; round < 20000; round += 1) {
      const length = Math.floor(random() * 15);
      let text = "";
      for (let i = 0; i < length; i += 1) text += PIECES[Math.floor(random() * PIECES.length)];
      const expected = [...text.matchAll(REFERENCE)].map((match) => [
        match.index,
        match.index + match[0].length,
        match[1] ?? null,
        match[2] ?? null,
      ]);
      const actual = scan(text).map((token) => [token.start, token.end, token.name, token.default]);
      expect(actual, JSON.stringify(text)).toEqual(expected);
    }
  });

  it("handles names at the 64-character limit like the reference", () => {
    for (const size of [63, 64, 65]) {
      const text = `{{${"a".repeat(size)}}} {{${"b".repeat(size)}|d}}`;
      const expected = [...text.matchAll(REFERENCE)].map((match) => match[0]);
      expect(scan(text).map((token) => text.slice(token.start, token.end))).toEqual(expected);
    }
  });

  it.each([
    ["unterminated defaults", "{{a|".repeat(25_000)],
    // A "}}" at the very end keeps the main loop busy on every line.
    ["unterminated defaults on many lines", `${"{{a|".repeat(2_500)}\n`.repeat(10) + "}}"],
  ])("stays fast on %s that made the regex quadratic", (_name, hostile) => {
    const started = performance.now();
    extractVariables(hostile, hostile);
    expect(renderTemplate(hostile, hostile, {}).prompt).toBe(hostile);
    // The regex needed about 4 s per 100,000 characters; the bound is loose for slow CI machines.
    expect(performance.now() - started).toBeLessThan(2000);
  });
});
