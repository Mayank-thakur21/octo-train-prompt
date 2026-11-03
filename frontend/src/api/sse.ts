/**
 * Server-Sent Events over `fetch` POST (contract section 8.3).
 * `EventSource` only supports GET, so the response body is read and parsed manually.
 */
import { abortError, ApiError, buildHeaders, buildUrl, errorFromResponse, isAbortError, safeFetch } from "./client";

/** One parsed SSE frame. `data` is the JSON-decoded payload. */
export interface SseMessage {
  event: string;
  data: unknown;
}

export interface StreamPostOptions {
  signal?: AbortSignal | undefined;
  /** Called for every frame with data (restricted to `events` when given). */
  onEvent: (message: SseMessage) => void;
  /** Event names the caller understands; other events are ignored. */
  events?: readonly string[];
}

/** Events that end a stream; the promise resolves right after dispatching one. */
const TERMINAL_EVENTS = new Set(["done", "error"]);

/**
 * Incremental SSE frame parser. Feed decoded text with `push`; complete frames
 * (terminated by a blank line) are returned. Handles `\r\n` / `\r` line endings
 * split across chunks, comment lines (`: ping`) and multi-line `data:` fields.
 */
export class SseParser {
  private buffer = "";
  private pendingCarriageReturn = false;

  push(text: string): Array<{ event: string; data: string }> {
    let chunk = text;
    if (this.pendingCarriageReturn) {
      chunk = `\r${chunk}`;
      this.pendingCarriageReturn = false;
    }
    // A trailing "\r" may be the first half of "\r\n": keep it for the next chunk.
    if (chunk.endsWith("\r")) {
      chunk = chunk.slice(0, -1);
      this.pendingCarriageReturn = true;
    }
    this.buffer += chunk.replace(/\r\n?/g, "\n");
    const frames: Array<{ event: string; data: string }> = [];
    let boundary = this.buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const frame = parseFrame(this.buffer.slice(0, boundary));
      this.buffer = this.buffer.slice(boundary + 2);
      if (frame) frames.push(frame);
      boundary = this.buffer.indexOf("\n\n");
    }
    return frames;
  }
}

/** Parses the lines of one frame. Frames without `data:` (comments, pings) yield null. */
function parseFrame(block: string): { event: string; data: string } | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line === "" || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length > 0 ? { event, data: data.join("\n") } : null;
}

/**
 * POSTs `body` as JSON and dispatches SSE frames until a terminal event.
 * Throws `ApiError` for non-2xx / non-SSE responses (error envelope) and for
 * streams that end without `done`/`error` (`stream_interrupted`); rethrows
 * an `AbortError` when `signal` aborts.
 */
export async function streamPost(path: string, body: unknown, options: StreamPostOptions): Promise<void> {
  const { signal, onEvent, events } = options;
  const response = await safeFetch(buildUrl(path), {
    method: "POST",
    headers: buildHeaders({ json: true, accept: "text/event-stream" }),
    body: JSON.stringify(body),
    signal: signal ?? null,
  });
  const contentType = response.headers.get("Content-Type") ?? "";
  if (!response.ok || !contentType.toLowerCase().includes("text/event-stream")) {
    throw await errorFromResponse(response);
  }
  if (!response.body) {
    throw new ApiError(0, "stream_interrupted", "The stream ended unexpectedly.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  const parser = new SseParser();
  const allowed = events ? new Set(events) : null;
  const onAbort = (): void => {
    reader.cancel().catch(() => undefined);
  };
  signal?.addEventListener("abort", onAbort, { once: true });

  /** Dispatches parsed frames; returns true once a terminal event was handled. */
  const dispatch = (frames: Array<{ event: string; data: string }>): boolean => {
    for (const frame of frames) {
      if (allowed && !allowed.has(frame.event)) continue;
      let data: unknown;
      try {
        data = JSON.parse(frame.data);
      } catch {
        throw new ApiError(0, "internal_error", "Unexpected server response.");
      }
      onEvent({ event: frame.event, data });
      if (TERMINAL_EVENTS.has(frame.event)) return true;
    }
    return false;
  };

  try {
    if (signal?.aborted) throw abortError();
    for (;;) {
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try {
        chunk = await reader.read();
      } catch (error) {
        if (signal?.aborted || isAbortError(error)) throw abortError();
        throw new ApiError(0, "stream_interrupted", "The stream ended unexpectedly.");
      }
      if (signal?.aborted) throw abortError();
      if (chunk.done) break;
      if (dispatch(parser.push(decoder.decode(chunk.value, { stream: true })))) {
        reader.cancel().catch(() => undefined);
        return;
      }
    }
    // Flush the decoder. Per the SSE rules an unterminated trailing frame is discarded.
    if (dispatch(parser.push(decoder.decode()))) return;
    throw new ApiError(0, "stream_interrupted", "The stream ended unexpectedly.");
  } finally {
    signal?.removeEventListener("abort", onAbort);
  }
}
