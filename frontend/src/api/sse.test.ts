import { describe, expect, it, vi } from "vitest";
import { apiError, controlledSse, json, mockApi, route, sseFrame, sseResponse } from "../test/fetchMock";
import { ApiError } from "./client";
import { SseParser, streamPost, type SseMessage } from "./sse";

/** Runs streamPost against a fixed response and collects the dispatched events. */
async function collect(response: Response, options: { events?: string[] } = {}): Promise<SseMessage[]> {
  mockApi([route("POST", "/api/runs/stream", () => response)]);
  const events: SseMessage[] = [];
  await streamPost("/runs/stream", { prompt: "x" }, { onEvent: (event) => events.push(event), ...options });
  return events;
}

describe("SseParser", () => {
  it("handles frames split across arbitrary chunk boundaries", () => {
    const parser = new SseParser();
    const text = sseFrame("delta", { type: "text", text: "Hel" }) + sseFrame("delta", { type: "text", text: "lo" });
    const frames = [];
    for (const char of text) frames.push(...parser.push(char));
    expect(frames).toEqual([
      { event: "delta", data: '{"type":"text","text":"Hel"}' },
      { event: "delta", data: '{"type":"text","text":"lo"}' },
    ]);
  });

  it("normalises CRLF, including a CR at the end of a chunk", () => {
    const parser = new SseParser();
    expect(parser.push("event: start\r\ndata: {}\r")).toEqual([]);
    expect(parser.push("\n\r\n")).toEqual([{ event: "start", data: "{}" }]);
  });

  it("joins multiple data lines and ignores comments and pings", () => {
    const parser = new SseParser();
    expect(parser.push(": ping\n\nevent: x\n: comment\ndata: [1,\ndata: 2]\nid: 7\n\n")).toEqual([{ event: "x", data: "[1,\n2]" }]);
  });
});

describe("streamPost()", () => {
  it("dispatches events until the terminal event", async () => {
    const body =
      sseFrame("start", { run_id: null }) + ": ping\n\n" + sseFrame("delta", { type: "text", text: "Hi" }) + sseFrame("done", { ok: 1 });
    const events = await collect(sseResponse([body.slice(0, 7), body.slice(7, 40), body.slice(40)]));
    expect(events.map((event) => event.event)).toEqual(["start", "delta", "done"]);
    expect(events[1]?.data).toEqual({ type: "text", text: "Hi" });
  });

  it("sends the SSE Accept header and JSON body", async () => {
    const api = mockApi([route("POST", "/api/runs/stream", () => sseResponse([sseFrame("done", {})]))]);
    await streamPost("/runs/stream", { prompt: "x" }, { onEvent: () => undefined });
    expect(api.calls[0]?.headers.get("Accept")).toBe("text/event-stream");
    expect(api.calls[0]?.body).toEqual({ prompt: "x" });
  });

  it("decodes multi-byte UTF-8 characters split between chunks", async () => {
    const bytes = new TextEncoder().encode(sseFrame("done", { text: "héllo ✓" }));
    const cut = bytes.indexOf(0xc3) + 1; // split inside "é"
    const events = await collect(sseResponse([bytes.slice(0, cut), bytes.slice(cut)]));
    expect(events[0]?.data).toEqual({ text: "héllo ✓" });
  });

  it("handles CRLF line endings", async () => {
    const events = await collect(sseResponse(["event: done\r\n", "data: {\"a\":1}\r\n\r\n"]));
    expect(events).toEqual([{ event: "done", data: { a: 1 } }]);
  });

  it("ignores unknown events when a whitelist is given", async () => {
    const events = await collect(sseResponse([sseFrame("mystery", { x: 1 }) + sseFrame("done", {})]), {
      events: ["start", "done"],
    });
    expect(events.map((event) => event.event)).toEqual(["done"]);
  });

  it("resolves after an error event", async () => {
    const events = await collect(sseResponse([sseFrame("error", { error: { code: "provider_error", message: "x" } })]));
    expect(events[0]?.event).toBe("error");
  });

  it("throws the error envelope of a non-2xx response", async () => {
    mockApi([
      route("POST", "/api/runs/stream", () =>
        apiError(422, "missing_variables", "Missing template variables.", { missing: ["name"] }),
      ),
    ]);
    await expect(streamPost("/runs/stream", {}, { onEvent: () => undefined })).rejects.toMatchObject({
      status: 422,
      code: "missing_variables",
      details: { missing: ["name"] },
    });
  });

  it("treats a 2xx JSON response as an error envelope", async () => {
    mockApi([route("POST", "/api/runs/stream", () => json({ hello: "world" }))]);
    await expect(streamPost("/runs/stream", {}, { onEvent: () => undefined })).rejects.toMatchObject({
      code: "internal_error",
    });
  });

  it("throws stream_interrupted when the body ends without a terminal event", async () => {
    const promise = collect(sseResponse([sseFrame("start", {}), "event: delta\ndata: {\"type\":\"te"]));
    await expect(promise).rejects.toBeInstanceOf(ApiError);
    await expect(promise).rejects.toMatchObject({ status: 0, code: "stream_interrupted" });
  });

  it("rethrows an AbortError when the signal aborts mid-stream and cancels the body", async () => {
    const stream = controlledSse();
    mockApi([route("POST", "/api/runs/stream", () => stream.response)]);
    const controller = new AbortController();
    const onEvent = vi.fn();
    const promise = streamPost("/runs/stream", {}, { signal: controller.signal, onEvent });
    stream.push(sseFrame("start", { run_id: null }));
    await vi.waitFor(() => expect(onEvent).toHaveBeenCalledTimes(1));
    controller.abort();
    await expect(promise).rejects.toMatchObject({ name: "AbortError" });
    expect(stream.cancelled()).toBe(true);
  });

  it("maps a stream read failure to stream_interrupted", async () => {
    const body = new ReadableStream<Uint8Array>({
      pull(controller) {
        controller.error(new TypeError("network lost"));
      },
    });
    mockApi([
      route("POST", "/api/runs/stream", () => new Response(body, { headers: { "Content-Type": "text/event-stream" } })),
    ]);
    await expect(streamPost("/runs/stream", {}, { onEvent: () => undefined })).rejects.toMatchObject({
      code: "stream_interrupted",
    });
  });

  it("maps malformed JSON data to internal_error", async () => {
    await expect(collect(sseResponse(["event: done\ndata: {nope\n\n"]))).rejects.toMatchObject({ code: "internal_error" });
  });
});
