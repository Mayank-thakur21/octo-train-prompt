/**
 * `fetch` mocking for tests: routes by method + path, records calls and builds
 * JSON, error-envelope and SSE responses. No real network is ever used.
 */
import { vi } from "vitest";

export interface MockRequest {
  method: string;
  url: URL;
  /** JSON-decoded body (undefined when there is none). */
  body: unknown;
  headers: Headers;
  signal: AbortSignal | null;
}

export type MockHandler = (request: MockRequest) => Response | Promise<Response>;

export interface MockRoute {
  method: string;
  /** Exact pathname (e.g. "/api/models") or a pattern. */
  path: string | RegExp;
  handler: MockHandler;
}

/** JSON response helper. */
export function json(data: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

/** Error-envelope response helper. */
export function apiError(
  status: number,
  code: string,
  message: string,
  details?: Record<string, unknown>,
  headers: Record<string, string> = {},
): Response {
  return json({ error: { code, message, ...(details ? { details } : {}) } }, status, headers);
}

/** Formats one SSE frame. */
export function sseFrame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

export interface ControlledStream {
  response: Response;
  /** Enqueues raw text (UTF-8 encoded). */
  push: (text: string) => void;
  close: () => void;
  /** True once the consumer cancelled the stream (e.g. after Stop). */
  cancelled: () => boolean;
}

/** SSE response whose chunks are pushed by the test, at arbitrary boundaries. */
export function controlledSse(): ControlledStream {
  const encoder = new TextEncoder();
  let controller: ReadableStreamDefaultController<Uint8Array> | null = null;
  let wasCancelled = false;
  let closed = false;
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
    cancel() {
      wasCancelled = true;
    },
  });
  return {
    response: new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream; charset=utf-8" } }),
    push: (text) => {
      if (!closed && !wasCancelled) controller?.enqueue(encoder.encode(text));
    },
    close: () => {
      if (!closed && !wasCancelled) {
        closed = true;
        controller?.close();
      }
    },
    cancelled: () => wasCancelled,
  };
}

/** SSE response with fixed chunks (already split however the test likes). */
export function sseResponse(chunks: Array<string | Uint8Array>): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(typeof chunk === "string" ? encoder.encode(chunk) : chunk);
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

function toUrl(input: RequestInfo | URL): URL {
  if (input instanceof URL) return input;
  if (typeof input === "string") return new URL(input, "http://localhost");
  return new URL(input.url, "http://localhost");
}

/** Installs a routed `fetch` mock. Unmatched requests get a 404 envelope so failures are visible. */
export function mockApi(routes: MockRoute[]) {
  const calls: MockRequest[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> => {
    const url = toUrl(input);
    const method = (init.method ?? "GET").toUpperCase();
    const body = typeof init.body === "string" && init.body !== "" ? (JSON.parse(init.body) as unknown) : undefined;
    const request: MockRequest = {
      method,
      url,
      body,
      headers: new Headers(init.headers),
      signal: init.signal ?? null,
    };
    calls.push(request);
    if (init.signal?.aborted) throw new DOMException("The operation was aborted.", "AbortError");
    const route = routes.find(
      (item) =>
        item.method === method && (typeof item.path === "string" ? item.path === url.pathname : item.path.test(url.pathname)),
    );
    if (!route) return apiError(404, "not_found", `No mock for ${method} ${url.pathname}`);
    return route.handler(request);
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    fetchMock,
    calls,
    /** Requests matching a method and exact path. */
    callsTo: (method: string, path: string) => calls.filter((call) => call.method === method && call.url.pathname === path),
  };
}

/** Convenience route builder: a handler, a Response (cloned per call) or JSON data. */
export function route(method: string, path: string | RegExp, handler: MockHandler): MockRoute;
export function route(method: string, path: string | RegExp, response: Response): MockRoute;
export function route(method: string, path: string | RegExp, data: object): MockRoute;
export function route(method: string, path: string | RegExp, value: MockHandler | Response | object): MockRoute {
  let handler: MockHandler;
  if (typeof value === "function") handler = value as MockHandler;
  else if (value instanceof Response) handler = () => value.clone();
  else handler = () => json(value);
  return { method, path, handler };
}
