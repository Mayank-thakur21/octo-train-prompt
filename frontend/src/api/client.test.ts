import { describe, expect, it, vi } from "vitest";
import { STORAGE_KEYS, writeStorage } from "../lib/storage";
import { apiError, json, mockApi, route } from "../test/fetchMock";
import { toastForError } from "../context/toast";
import { ApiError, buildUrl, errorFromEnvelope, parseRetryAfter, request } from "./client";

describe("request()", () => {
  it("sends JSON headers and the stored API key", async () => {
    writeStorage(STORAGE_KEYS.apiKey, "secret-key-1234567890");
    const api = mockApi([route("POST", "/api/runs", { ok: true })]);
    await expect(request("POST", "/runs", { body: { prompt: "hi" } })).resolves.toEqual({ ok: true });
    const call = api.calls[0];
    expect(call?.headers.get("Accept")).toBe("application/json");
    expect(call?.headers.get("Content-Type")).toBe("application/json");
    expect(call?.headers.get("X-API-Key")).toBe("secret-key-1234567890");
    expect(call?.body).toEqual({ prompt: "hi" });
  });

  it("omits Content-Type without a body and X-API-Key without a stored key", async () => {
    const api = mockApi([route("GET", "/api/models", { models: [] })]);
    await request("GET", "/models");
    expect(api.calls[0]?.headers.has("Content-Type")).toBe(false);
    expect(api.calls[0]?.headers.has("X-API-Key")).toBe(false);
  });

  it("resolves 204 responses to undefined", async () => {
    mockApi([route("DELETE", "/api/history/x", () => new Response(null, { status: 204 }))]);
    await expect(request("DELETE", "/history/x")).resolves.toBeUndefined();
  });

  it("turns error envelopes into ApiError with details and Retry-After", async () => {
    mockApi([
      route("POST", "/api/runs", () => apiError(429, "rate_limited", "Too many requests.", { retry_after: 9 }, { "Retry-After": "12" })),
    ]);
    const error = await request("POST", "/runs", { body: {} }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 429, code: "rate_limited", message: "Too many requests.", retryAfter: 12 });
    expect((error as ApiError).details).toEqual({ retry_after: 9 });
  });

  it("falls back to details.retry_after when the header is missing", () => {
    const error = errorFromEnvelope({ error: { code: "provider_rate_limited", message: "m", details: { retry_after: 6.2 } } }, 429);
    expect(error?.retryAfter).toBe(7);
  });

  it("maps an unparseable error body to internal_error", async () => {
    mockApi([route("GET", "/api/meta", () => new Response("<html>oops</html>", { status: 500 }))]);
    await expect(request("GET", "/meta")).rejects.toMatchObject({
      status: 500,
      code: "internal_error",
      message: "Unexpected server response.",
    });
  });

  it.each([502, 503, 504])("maps a proxy's %i error page to backend_unavailable (the server is unreachable)", async (status) => {
    mockApi([route("GET", "/api/meta", () => new Response("<html>502 Bad Gateway</html>", { status }))]);
    const error = await request("GET", "/meta").catch((caught: unknown) => caught);
    expect(error).toMatchObject({
      status,
      code: "backend_unavailable",
      message: "The API server is not reachable. Try again shortly.",
    });
    expect(toastForError(error)).toMatchObject({ id: "global-network", title: "Cannot reach the server." });
  });

  it("keeps the API's own 502/503 envelopes (provider errors) unchanged", async () => {
    mockApi([
      route("GET", "/api/meta", () =>
        Response.json({ error: { code: "provider_overloaded", message: "The Anthropic API is temporarily overloaded." } }, { status: 503 }),
      ),
    ]);
    const error = await request("GET", "/meta").catch((caught: unknown) => caught);
    expect(error).toMatchObject({ status: 503, code: "provider_overloaded" });
    expect(toastForError(error)).toBeNull();
  });

  it("maps a 2xx response that is not JSON to internal_error", async () => {
    mockApi([route("GET", "/api/meta", () => new Response("oops", { status: 200 }))]);
    await expect(request("GET", "/meta")).rejects.toMatchObject({ code: "internal_error" });
  });

  it("maps fetch rejections to network_error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(request("GET", "/meta")).rejects.toMatchObject({
      status: 0,
      code: "network_error",
      message: "Cannot reach the server.",
    });
  });

  it("rethrows aborts unchanged", async () => {
    const controller = new AbortController();
    controller.abort();
    mockApi([route("GET", "/api/meta", json({}))]);
    await expect(request("GET", "/meta", { signal: controller.signal })).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("buildUrl()", () => {
  it("repeats array values and skips empty ones", () => {
    expect(buildUrl("/prompts", { q: "", tag: ["a", "b"], archived: "all", limit: 20, offset: undefined, x: null })).toBe(
      "/api/prompts?tag=a&tag=b&archived=all&limit=20",
    );
    expect(buildUrl("/meta")).toBe("/api/meta");
  });
});

describe("parseRetryAfter()", () => {
  it("parses delta seconds and HTTP dates", () => {
    expect(parseRetryAfter("5")).toBe(5);
    expect(parseRetryAfter(null)).toBeNull();
    expect(parseRetryAfter("garbage")).toBeNull();
    const future = new Date(Date.now() + 10_000).toUTCString();
    expect(parseRetryAfter(future)).toBeGreaterThanOrEqual(8);
  });
});
