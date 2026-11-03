import { describe, expect, it } from "vitest";
import { runResult } from "../test/fixtures";
import { json, mockApi, route, sseFrame, sseResponse } from "../test/fetchMock";
import {
  exportData,
  filenameFromDisposition,
  importData,
  listHistory,
  listPrompts,
  restoreVersion,
  streamCompare,
  streamRun,
} from "./endpoints";
import type { ExportDocument } from "./types";

describe("endpoints", () => {
  it("streamRun reports start/deltas and resolves with the done payload", async () => {
    const done = runResult({ text: "Hi there" });
    mockApi([
      route("POST", "/api/runs/stream", () =>
        sseResponse([
          sseFrame("start", { run_id: "r", model: "m", provider: "demo", created_at: done.created_at, warnings: [] }),
          sseFrame("delta", { type: "thinking", text: "hmm" }),
          sseFrame("delta", { type: "text", text: "Hi " }),
          sseFrame("delta", { type: "text", text: "there" }),
          sseFrame("done", done),
        ]),
      ),
    ]);
    const deltas: string[] = [];
    let started = false;
    const result = await streamRun(
      { prompt: "x" },
      { onStart: () => (started = true), onDelta: (delta) => deltas.push(`${delta.type}:${delta.text}`) },
    );
    expect(started).toBe(true);
    expect(deltas).toEqual(["thinking:hmm", "text:Hi ", "text:there"]);
    expect(result.text).toBe("Hi there");
  });

  it("streamRun rejects with the error event envelope (status from the code)", async () => {
    mockApi([
      route("POST", "/api/runs/stream", () =>
        sseResponse([
          sseFrame("start", { run_id: "r" }),
          sseFrame("error", {
            error: { code: "provider_rate_limited", message: "Rate limited.", details: { run_id: "r", retry_after: 7 } },
          }),
        ]),
      ),
    ]);
    await expect(streamRun({ prompt: "x" }, {})).rejects.toMatchObject({
      status: 429,
      code: "provider_rate_limited",
      retryAfter: 7,
      details: { run_id: "r", retry_after: 7 },
    });
  });

  it("streamCompare forwards cell events", async () => {
    mockApi([
      route("POST", "/api/compare/stream", () =>
        sseResponse([
          sseFrame("start", { comparison_id: "c", created_at: "t", cells: [], warnings: [] }),
          sseFrame("cell", { index: 1 }),
          sseFrame("cell", { index: 0 }),
          sseFrame("done", { id: "c", cells: [] }),
        ]),
      ),
    ]);
    const cells: number[] = [];
    const result = await streamCompare({ variants: [{ prompt: "x" }], models: ["m"] }, { onCell: (cell) => cells.push(cell.index) });
    expect(cells).toEqual([1, 0]);
    expect(result.id).toBe("c");
  });

  it("listPrompts repeats tag parameters", async () => {
    const api = mockApi([route("GET", "/api/prompts", { items: [], total: 0, limit: 20, offset: 0 })]);
    await listPrompts({ q: "sum", tag: ["writing", "code"], archived: "all", limit: 20, offset: 40 });
    const url = api.calls[0]?.url;
    expect(url?.searchParams.getAll("tag")).toEqual(["writing", "code"]);
    expect(url?.searchParams.get("q")).toBe("sum");
    expect(url?.searchParams.get("offset")).toBe("40");
  });

  it("listHistory passes filters as query parameters", async () => {
    const api = mockApi([route("GET", "/api/history", { items: [], total: 0, limit: 20, offset: 0 })]);
    await listHistory({ model: "demo-concise", status: "error", source: "compare", group_id: "g" });
    expect(Object.fromEntries(api.calls[0]?.url.searchParams ?? [])).toEqual({
      model: "demo-concise",
      status: "error",
      source: "compare",
      group_id: "g",
    });
  });

  it("restoreVersion posts without a body", async () => {
    const api = mockApi([route("POST", "/api/prompts/p/versions/2/restore", json({ version: 3 }, 201))]);
    await expect(restoreVersion("p", 2)).resolves.toEqual({ version: 3 });
    expect(api.calls[0]?.body).toBeUndefined();
  });

  it("exportData returns the blob and the filename from Content-Disposition", async () => {
    const api = mockApi([
      route("GET", "/api/export", () =>
        json({ format: "prompt-studio-export" }, 200, {
          "Content-Disposition": 'attachment; filename="prompt-studio-export-20261103-091502.json"',
        }),
      ),
    ]);
    const result = await exportData(["prompts", "history"]);
    expect(api.calls[0]?.url.searchParams.get("include")).toBe("prompts,history");
    expect(result.filename).toBe("prompt-studio-export-20261103-091502.json");
    expect(JSON.parse(await result.blob.text())).toEqual({ format: "prompt-studio-export" });
  });

  it("parses RFC 5987 and fallback filenames", () => {
    expect(filenameFromDisposition("attachment; filename*=UTF-8''a%20b.json", "x")).toBe("a b.json");
    expect(filenameFromDisposition(null, "fallback.json")).toBe("fallback.json");
  });

  it("importData sends the document with the conflict policy", async () => {
    const api = mockApi([
      route("POST", "/api/import", {
        prompts: { created: 1, updated: 0, skipped: 0, renamed: 0 },
        suites: { created: 0, updated: 0, skipped: 0, renamed: 0 },
        history: { created: 0 },
        warnings: [],
      }),
    ]);
    const doc = { format: "prompt-studio-export", format_version: 1 } as unknown as ExportDocument;
    await importData(doc, "rename", true);
    const call = api.calls[0];
    expect(call?.url.searchParams.get("conflict")).toBe("rename");
    expect(call?.url.searchParams.get("legacy_placeholders")).toBe("true");
    expect(call?.body).toEqual(doc);
  });
});
