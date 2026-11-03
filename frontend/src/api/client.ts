/**
 * Minimal typed HTTP client for the Prompt Studio API (contract section 8.3).
 * All requests go to the relative `/api` base, carry the stored API key and
 * turn error envelopes into `ApiError` instances.
 */
import { isRecord, readStorage, STORAGE_KEYS } from "../lib/storage";

/** API base path. Relative on purpose: the dev proxy and nginx forward it to the backend. */
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/api";

/** Error raised for every failed API call (HTTP errors, network failures, broken streams). */
export class ApiError extends Error {
  override readonly name = "ApiError";
  /** HTTP status; 0 for client-side failures (network, interrupted stream, abort). */
  readonly status: number;
  /** Stable machine code from the error envelope (or a FE pseudo code). */
  readonly code: string;
  /** Optional structured details from the envelope. */
  readonly details: Record<string, unknown> | null;
  /** Seconds to wait before retrying, from `Retry-After` (or `details.retry_after`). */
  readonly retryAfter: number | null;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> | null = null,
    retryAfter: number | null = null,
  ) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.retryAfter = retryAfter;
  }
}

/** Returns true for errors produced by an aborted fetch or stream. */
export function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  );
}

/** Creates the DOMException used to signal an aborted request. */
export function abortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}

/** API key saved in Settings ("" when none). */
export function getStoredApiKey(): string {
  return readStorage(STORAGE_KEYS.apiKey, "", (v): v is string => typeof v === "string").trim();
}

/** Builds request headers: Accept, optional JSON content type and the stored API key. */
export function buildHeaders(options: { accept?: string; json?: boolean } = {}): Headers {
  const headers = new Headers();
  headers.set("Accept", options.accept ?? "application/json");
  if (options.json) headers.set("Content-Type", "application/json");
  const apiKey = getStoredApiKey();
  if (apiKey) headers.set("X-API-Key", apiKey);
  return headers;
}

export type QueryValue = string | number | boolean | null | undefined | ReadonlyArray<string | number>;
export type Query = Record<string, QueryValue>;

/** Joins the API base, a path and query parameters. Arrays become repeated keys; empty values are skipped. */
export function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams();
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === null || value === undefined || value === "") continue;
      if (Array.isArray(value)) {
        for (const item of value as ReadonlyArray<string | number>) params.append(key, String(item));
      } else {
        params.append(key, String(value));
      }
    }
  }
  const qs = params.toString();
  return `${API_BASE}${path}${qs ? `?${qs}` : ""}`;
}

/** Parses `Retry-After` (delta seconds or HTTP date) into whole seconds. */
export function parseRetryAfter(value: string | null): number | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (/^\d+$/.test(trimmed)) return Number.parseInt(trimmed, 10);
  const date = Date.parse(trimmed);
  if (Number.isNaN(date)) return null;
  return Math.max(0, Math.ceil((date - Date.now()) / 1000));
}

/** Converts an error envelope payload into an `ApiError`, or null when the shape is wrong. */
export function errorFromEnvelope(payload: unknown, status: number, retryAfter: number | null = null): ApiError | null {
  if (!isRecord(payload) || !isRecord(payload.error)) return null;
  const { code, message, details } = payload.error;
  if (typeof code !== "string" || typeof message !== "string") return null;
  const detailRecord = isRecord(details) ? details : null;
  let wait = retryAfter;
  if (wait === null && detailRecord && typeof detailRecord.retry_after === "number") {
    wait = Math.ceil(detailRecord.retry_after);
  }
  return new ApiError(status, code, message, detailRecord, wait);
}

/** Statuses a proxy in front of the API uses when it cannot reach it. */
const GATEWAY_STATUSES = new Set([502, 503, 504]);
const BACKEND_UNAVAILABLE_MESSAGE = "The API server is not reachable. Try again shortly.";

/** Reads a non-2xx response and builds the matching `ApiError`. */
export async function errorFromResponse(response: Response): Promise<ApiError> {
  const retryAfter = parseRetryAfter(response.headers.get("Retry-After"));
  let payload: unknown;
  try {
    payload = JSON.parse(await response.text());
  } catch {
    payload = null;
  }
  const fromApi = errorFromEnvelope(payload, response.status, retryAfter);
  if (fromApi) return fromApi;
  // A gateway (nginx, a load balancer) answered with its own error page: the API is unreachable.
  if (GATEWAY_STATUSES.has(response.status)) {
    return new ApiError(response.status, "backend_unavailable", BACKEND_UNAVAILABLE_MESSAGE, null, retryAfter);
  }
  return new ApiError(response.status, "internal_error", "Unexpected server response.", null, retryAfter);
}

/** Wraps `fetch`: rethrows aborts, maps every other rejection to `network_error`. */
export async function safeFetch(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (error) {
    if (isAbortError(error) || init.signal?.aborted) throw error;
    throw new ApiError(0, "network_error", "Cannot reach the server.");
  }
}

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface RequestOptions {
  body?: unknown;
  query?: Query;
  signal?: AbortSignal | undefined;
}

/** Performs the request and returns the raw successful response (non-2xx throws `ApiError`). */
export async function requestResponse(method: HttpMethod, path: string, options: RequestOptions = {}): Promise<Response> {
  const hasBody = options.body !== undefined;
  const init: RequestInit = {
    method,
    headers: buildHeaders({ json: hasBody }),
    body: hasBody ? JSON.stringify(options.body) : null,
    signal: options.signal ?? null,
  };
  const response = await safeFetch(buildUrl(path, options.query), init);
  if (!response.ok) throw await errorFromResponse(response);
  return response;
}

/**
 * Sends a JSON request and decodes the JSON response.
 * 204 resolves to `undefined`; a 2xx response that is not valid JSON is an `internal_error`.
 */
export async function request<T>(method: HttpMethod, path: string, options: RequestOptions = {}): Promise<T> {
  const response = await requestResponse(method, path, options);
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(response.status, "internal_error", "Unexpected server response.");
  }
}
