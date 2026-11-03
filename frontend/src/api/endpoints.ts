/**
 * One typed function per backend endpoint (contract section 2.5).
 * Path ids are URL-encoded; list endpoints take typed parameter objects.
 */
import { ApiError, errorFromEnvelope, request, requestResponse } from "./client";
import { streamPost } from "./sse";
import type {
  CaseInput,
  CompareCell,
  CompareRequest,
  CompareResult,
  CompareStartEvent,
  DeletedCount,
  EvalCreate,
  EvalRunDetail,
  EvalRunSummary,
  EvalStatus,
  ExportDocument,
  HealthResponse,
  HistoryDetail,
  HistorySource,
  HistoryStatus,
  HistorySummary,
  ID,
  ImportResult,
  Meta,
  ModelsResponse,
  Page,
  PromptCreate,
  PromptDetail,
  PromptSummary,
  PromptUpdate,
  ProviderId,
  ReadyResponse,
  RenderRequest,
  RenderResult,
  RunDeltaEvent,
  RunRequest,
  RunResult,
  RunStartEvent,
  SuiteCreate,
  SuiteDetail,
  SuiteSummary,
  SuiteUpdate,
  TagsResponse,
  TemplatesResponse,
  TestCase,
  TokenEstimate,
  TokenEstimateRequest,
  VersionCreate,
  VersionDetail,
  VersionDiff,
  VersionSummary,
} from "./types";

const id = (value: string): string => encodeURIComponent(value);

/** Common pagination parameters (`limit` 1..100, `offset` >= 0). */
export interface PageParams {
  limit?: number;
  offset?: number;
}

/** HTTP status the backend uses for each error code; used for errors delivered inside SSE streams. */
const STATUS_BY_CODE: Record<string, number> = {
  provider_rate_limited: 429,
  provider_auth_error: 502,
  provider_invalid_request: 400,
  provider_overloaded: 503,
  provider_timeout: 504,
  provider_error: 502,
  internal_error: 500,
};

/** Builds an `ApiError` from an SSE `error` event payload. */
function streamError(payload: unknown): ApiError {
  const code =
    typeof payload === "object" && payload !== null && "error" in payload
      ? (payload as { error: { code?: unknown } }).error.code
      : undefined;
  const status = typeof code === "string" ? (STATUS_BY_CODE[code] ?? 500) : 500;
  return (
    errorFromEnvelope(payload, status) ?? new ApiError(500, "internal_error", "Unexpected server response.")
  );
}

// ---------- meta ----------

export const getHealth = (signal?: AbortSignal): Promise<HealthResponse> =>
  request<HealthResponse>("GET", "/health", { signal });

export const getReady = (signal?: AbortSignal): Promise<ReadyResponse> =>
  request<ReadyResponse>("GET", "/ready", { signal });

export const getMeta = (signal?: AbortSignal): Promise<Meta> => request<Meta>("GET", "/meta", { signal });

export const getModels = (signal?: AbortSignal): Promise<ModelsResponse> =>
  request<ModelsResponse>("GET", "/models", { signal });

// ---------- runs ----------

export const runPrompt = (req: RunRequest, signal?: AbortSignal): Promise<RunResult> =>
  request<RunResult>("POST", "/runs", { body: req, signal });

export interface RunStreamHandlers {
  onStart?: (event: RunStartEvent) => void;
  onDelta?: (event: RunDeltaEvent) => void;
}

/**
 * Streams a run (`POST /api/runs/stream`). Resolves with the `done` payload;
 * an `error` event rejects with the corresponding `ApiError`.
 */
export async function streamRun(
  req: RunRequest,
  handlers: RunStreamHandlers,
  signal?: AbortSignal,
): Promise<RunResult> {
  const outcome: { result: RunResult | null; error: ApiError | null } = { result: null, error: null };
  await streamPost("/runs/stream", req, {
    signal,
    events: ["start", "delta", "done", "error"],
    onEvent: ({ event, data }) => {
      if (event === "start") handlers.onStart?.(data as RunStartEvent);
      else if (event === "delta") handlers.onDelta?.(data as RunDeltaEvent);
      else if (event === "done") outcome.result = data as RunResult;
      else outcome.error = streamError(data);
    },
  });
  if (outcome.error) throw outcome.error;
  if (!outcome.result) throw new ApiError(0, "stream_interrupted", "The stream ended unexpectedly.");
  return outcome.result;
}

export const estimateTokens = (req: TokenEstimateRequest, signal?: AbortSignal): Promise<TokenEstimate> =>
  request<TokenEstimate>("POST", "/tokens/estimate", { body: req, signal });

// ---------- templates ----------

export const getTemplates = (signal?: AbortSignal): Promise<TemplatesResponse> =>
  request<TemplatesResponse>("GET", "/templates", { signal });

export const renderTemplate = (req: RenderRequest, signal?: AbortSignal): Promise<RenderResult> =>
  request<RenderResult>("POST", "/templates/render", { body: req, signal });

// ---------- prompts ----------

export type ArchivedFilter = "false" | "true" | "all";
export type PromptSort = "updated_at" | "created_at" | "name";
export type SortOrder = "desc" | "asc";

export interface PromptListParams extends PageParams {
  q?: string;
  tag?: string[];
  archived?: ArchivedFilter;
  sort?: PromptSort;
  order?: SortOrder;
}

export const listPrompts = (params: PromptListParams = {}, signal?: AbortSignal): Promise<Page<PromptSummary>> =>
  request<Page<PromptSummary>>("GET", "/prompts", { query: { ...params }, signal });

export const createPrompt = (body: PromptCreate): Promise<PromptDetail> =>
  request<PromptDetail>("POST", "/prompts", { body });

export const getPrompt = (promptId: ID, signal?: AbortSignal): Promise<PromptDetail> =>
  request<PromptDetail>("GET", `/prompts/${id(promptId)}`, { signal });

export const updatePrompt = (promptId: ID, body: PromptUpdate): Promise<PromptDetail> =>
  request<PromptDetail>("PATCH", `/prompts/${id(promptId)}`, { body });

export const deletePrompt = (promptId: ID): Promise<void> =>
  request<void>("DELETE", `/prompts/${id(promptId)}`);

export const listVersions = (
  promptId: ID,
  params: PageParams = {},
  signal?: AbortSignal,
): Promise<Page<VersionSummary>> =>
  request<Page<VersionSummary>>("GET", `/prompts/${id(promptId)}/versions`, { query: { ...params }, signal });

export const createVersion = (promptId: ID, body: VersionCreate): Promise<VersionDetail> =>
  request<VersionDetail>("POST", `/prompts/${id(promptId)}/versions`, { body });

export const getVersion = (promptId: ID, version: number, signal?: AbortSignal): Promise<VersionDetail> =>
  request<VersionDetail>("GET", `/prompts/${id(promptId)}/versions/${version}`, { signal });

export const restoreVersion = (promptId: ID, version: number): Promise<VersionDetail> =>
  request<VersionDetail>("POST", `/prompts/${id(promptId)}/versions/${version}/restore`);

export const diffVersions = (
  promptId: ID,
  fromVersion: number,
  toVersion: number,
  signal?: AbortSignal,
): Promise<VersionDiff> =>
  request<VersionDiff>("GET", `/prompts/${id(promptId)}/diff`, {
    query: { from_version: fromVersion, to_version: toVersion },
    signal,
  });

export const getPromptVersion = (versionId: ID, signal?: AbortSignal): Promise<VersionDetail> =>
  request<VersionDetail>("GET", `/prompt-versions/${id(versionId)}`, { signal });

export const getTags = (signal?: AbortSignal): Promise<TagsResponse> =>
  request<TagsResponse>("GET", "/tags", { signal });

// ---------- compare ----------

export const runCompare = (req: CompareRequest, signal?: AbortSignal): Promise<CompareResult> =>
  request<CompareResult>("POST", "/compare", { body: req, signal });

export interface CompareStreamHandlers {
  onStart?: (event: CompareStartEvent) => void;
  onCell?: (cell: CompareCell) => void;
}

/** Streams a comparison (`POST /api/compare/stream`) and resolves with the `done` payload. */
export async function streamCompare(
  req: CompareRequest,
  handlers: CompareStreamHandlers,
  signal?: AbortSignal,
): Promise<CompareResult> {
  const outcome: { result: CompareResult | null; error: ApiError | null } = { result: null, error: null };
  await streamPost("/compare/stream", req, {
    signal,
    events: ["start", "cell", "done", "error"],
    onEvent: ({ event, data }) => {
      if (event === "start") handlers.onStart?.(data as CompareStartEvent);
      else if (event === "cell") handlers.onCell?.(data as CompareCell);
      else if (event === "done") outcome.result = data as CompareResult;
      else outcome.error = streamError(data);
    },
  });
  if (outcome.error) throw outcome.error;
  if (!outcome.result) throw new ApiError(0, "stream_interrupted", "The stream ended unexpectedly.");
  return outcome.result;
}

// ---------- suites ----------

export interface SuiteListParams extends PageParams {
  q?: string;
}

export const listSuites = (params: SuiteListParams = {}, signal?: AbortSignal): Promise<Page<SuiteSummary>> =>
  request<Page<SuiteSummary>>("GET", "/suites", { query: { ...params }, signal });

export const createSuite = (body: SuiteCreate): Promise<SuiteDetail> =>
  request<SuiteDetail>("POST", "/suites", { body });

export const getSuite = (suiteId: ID, signal?: AbortSignal): Promise<SuiteDetail> =>
  request<SuiteDetail>("GET", `/suites/${id(suiteId)}`, { signal });

export const updateSuite = (suiteId: ID, body: SuiteUpdate): Promise<SuiteDetail> =>
  request<SuiteDetail>("PATCH", `/suites/${id(suiteId)}`, { body });

export const deleteSuite = (suiteId: ID): Promise<void> => request<void>("DELETE", `/suites/${id(suiteId)}`);

export const createCase = (suiteId: ID, body: CaseInput): Promise<TestCase> =>
  request<TestCase>("POST", `/suites/${id(suiteId)}/cases`, { body });

export const updateCase = (suiteId: ID, caseId: ID, body: CaseInput): Promise<TestCase> =>
  request<TestCase>("PUT", `/suites/${id(suiteId)}/cases/${id(caseId)}`, { body });

export const deleteCase = (suiteId: ID, caseId: ID): Promise<void> =>
  request<void>("DELETE", `/suites/${id(suiteId)}/cases/${id(caseId)}`);

// ---------- evaluations ----------

export interface EvalListParams extends PageParams {
  suite_id?: ID;
  prompt_id?: ID;
  status?: EvalStatus;
}

export const startEval = (req: EvalCreate): Promise<EvalRunDetail> =>
  request<EvalRunDetail>("POST", "/evals", { body: req });

export const listEvals = (params: EvalListParams = {}, signal?: AbortSignal): Promise<Page<EvalRunSummary>> =>
  request<Page<EvalRunSummary>>("GET", "/evals", { query: { ...params }, signal });

export const getEval = (evalId: ID, signal?: AbortSignal): Promise<EvalRunDetail> =>
  request<EvalRunDetail>("GET", `/evals/${id(evalId)}`, { signal });

export const cancelEval = (evalId: ID): Promise<EvalRunSummary> =>
  request<EvalRunSummary>("POST", `/evals/${id(evalId)}/cancel`);

export const deleteEval = (evalId: ID): Promise<void> => request<void>("DELETE", `/evals/${id(evalId)}`);

// ---------- history ----------

export interface HistoryListParams extends PageParams {
  q?: string;
  model?: string;
  provider?: ProviderId;
  status?: HistoryStatus;
  source?: HistorySource;
  group_id?: ID;
}

export const listHistory = (params: HistoryListParams = {}, signal?: AbortSignal): Promise<Page<HistorySummary>> =>
  request<Page<HistorySummary>>("GET", "/history", { query: { ...params }, signal });

export const getHistoryItem = (historyId: ID, signal?: AbortSignal): Promise<HistoryDetail> =>
  request<HistoryDetail>("GET", `/history/${id(historyId)}`, { signal });

export const deleteHistoryItem = (historyId: ID): Promise<void> =>
  request<void>("DELETE", `/history/${id(historyId)}`);

export const clearHistory = (): Promise<DeletedCount> => request<DeletedCount>("DELETE", "/history");

// ---------- export / import ----------

export type ExportInclude = "prompts" | "suites" | "history";
export type ImportConflict = "skip" | "rename" | "overwrite";

/** Extracts the filename from a `Content-Disposition` header. */
export function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const star = /filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i.exec(header);
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1].trim().replace(/^"|"$/g, ""));
    } catch {
      // Malformed percent-encoding: fall through to the plain parameter.
    }
  }
  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(header);
  return plain?.[1]?.trim() ?? fallback;
}

/** Downloads an export document (`GET /api/export`) as a Blob plus its server-chosen filename. */
export async function exportData(include: ExportInclude[]): Promise<{ blob: Blob; filename: string }> {
  const response = await requestResponse("GET", "/export", { query: { include: include.join(",") } });
  const blob = await response.blob();
  return {
    blob,
    filename: filenameFromDisposition(response.headers.get("Content-Disposition"), "prompt-studio-export.json"),
  };
}

/** Imports an export document (`POST /api/import`). */
export const importData = (
  doc: ExportDocument,
  conflict: ImportConflict = "skip",
  legacyPlaceholders = false,
): Promise<ImportResult> =>
  request<ImportResult>("POST", "/import", {
    body: doc,
    query: { conflict, legacy_placeholders: legacyPlaceholders },
  });
