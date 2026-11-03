/**
 * Wire types shared with the backend (contract section 2.4).
 * Names and field spellings are part of the API contract: snake_case, no conversion.
 */

export type ID = string; // 32 lowercase hex
export type Timestamp = string; // "2026-11-03T09:15:02.123456Z"
export type ProviderId = "anthropic" | "openai" | "gemini" | "demo";
export type FinishReason = "stop" | "length" | "content_filter" | "refusal" | "other";

export interface ErrorBody {
  code: string;
  message: string;
  details?: Record<string, unknown> | null;
}
export interface ErrorEnvelope {
  error: ErrorBody;
}
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

// ---------- meta / models ----------
export interface Pricing {
  currency: "USD";
  input_per_mtok: number;
  output_per_mtok: number;
  long_context: {
    threshold_input_tokens: number;
    input_per_mtok: number;
    output_per_mtok: number;
  } | null;
}
export interface ModelInfo {
  id: string;
  provider: ProviderId;
  display_name: string;
  available: boolean;
  is_default: boolean;
  supports_thinking: boolean;
  thinking_always_on: boolean;
  supports_temperature: boolean;
  max_output_tokens: number;
  context_window: number | null;
  pricing: Pricing | null;
}
export interface ModelsResponse {
  models: ModelInfo[];
  default_model: string;
}
export interface ProviderInfo {
  id: ProviderId;
  display_name: string;
  configured: boolean;
}
export interface Limits {
  max_prompt_chars: number;
  max_system_chars: number;
  max_rendered_chars: number;
  max_variables: number;
  max_variable_value_chars: number;
  max_output_tokens: number;
  default_max_tokens: number;
  max_compare_variants: number;
  max_compare_models: number;
  max_compare_cells: number;
  max_cases_per_suite: number;
  max_assertions_per_case: number;
  max_eval_models: number;
  max_eval_calls: number;
  max_tags_per_prompt: number;
  max_versions_per_prompt: number;
  max_body_bytes: number;
  import_max_bytes: number;
  request_timeout_seconds: number;
}
export interface Meta {
  name: "Prompt Engineering Studio";
  version: string;
  auth_required: boolean;
  demo_mode: boolean;
  default_model: string;
  providers: ProviderInfo[];
  limits: Limits;
}
export interface HealthResponse {
  status: "ok";
  version: string;
  time: Timestamp;
}
export interface ReadyResponse {
  status: "ready";
  checks: Record<string, string>;
}

// ---------- templates ----------
export interface VariableInfo {
  name: string;
  default: string | null;
  required: boolean;
}
export interface BuiltinTemplate {
  id: string;
  name: string;
  description: string;
  tags: string[];
  system: string | null;
  prompt: string;
  variables: VariableInfo[];
}
export interface TemplatesResponse {
  templates: BuiltinTemplate[];
}
export interface RenderRequest {
  system?: string | null;
  prompt: string;
  variables?: Record<string, string>;
  strict?: boolean;
}
export interface RenderResult {
  system: string | null;
  prompt: string;
  variables: VariableInfo[];
  missing: string[];
}

// ---------- runs ----------
export interface RunParams {
  temperature: number | null;
  max_tokens: number;
  thinking: boolean;
}
export interface RunRequest {
  model?: string | null;
  system?: string | null;
  prompt: string;
  variables?: Record<string, string>;
  temperature?: number | null;
  max_tokens?: number | null;
  thinking?: boolean;
  prompt_version_id?: ID | null;
  save_history?: boolean;
}
export interface RunResult {
  id: ID | null;
  created_at: Timestamp;
  model: string;
  provider: ProviderId;
  text: string;
  thinking: string | null;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  ttft_ms: number | null;
  finish_reason: FinishReason;
  request_id: string | null;
  cost_usd: number | null;
  warnings: string[];
  rendered_system: string | null;
  rendered_prompt: string;
  params: RunParams;
}

// SSE payloads for POST /api/runs/stream
export interface RunStartEvent {
  run_id: ID | null;
  model: string;
  provider: ProviderId;
  created_at: Timestamp;
  warnings: string[];
}
export interface RunDeltaEvent {
  type: "text" | "thinking";
  text: string;
}
export type RunDoneEvent = RunResult;
export type RunErrorEvent = ErrorEnvelope;

// ---------- tokens ----------
export interface TokenEstimateRequest {
  model?: string | null;
  system?: string | null;
  prompt: string;
  variables?: Record<string, string>;
}
export interface TokenEstimate {
  model: string;
  provider: ProviderId;
  input_tokens: number;
  method: "heuristic" | "anthropic_count_tokens";
  characters: number;
  words: number;
  warnings: string[];
}

// ---------- prompts library ----------
export interface PromptSettings {
  model: string | null;
  temperature: number | null;
  max_tokens: number | null;
  thinking: boolean;
}
export interface VersionSummary {
  id: ID;
  prompt_id: ID;
  version: number;
  notes: string;
  created_at: Timestamp;
  variables: string[];
}
export interface VersionDetail {
  id: ID;
  prompt_id: ID;
  version: number;
  system: string | null;
  prompt: string;
  notes: string;
  settings: PromptSettings;
  variables: VariableInfo[];
  created_at: Timestamp;
}
export interface PromptSummary {
  id: ID;
  name: string;
  description: string;
  tags: string[];
  archived: boolean;
  created_at: Timestamp;
  updated_at: Timestamp;
  version_count: number;
  latest_version: VersionSummary;
}
export interface PromptDetail {
  id: ID;
  name: string;
  description: string;
  tags: string[];
  archived: boolean;
  created_at: Timestamp;
  updated_at: Timestamp;
  version_count: number;
  latest_version: VersionDetail;
}
export interface PromptCreate {
  name: string;
  description?: string;
  tags?: string[];
  system?: string | null;
  prompt: string;
  notes?: string;
  settings?: PromptSettings;
}
export interface PromptUpdate {
  name?: string;
  description?: string;
  tags?: string[];
  archived?: boolean;
}
export interface VersionCreate {
  system?: string | null;
  prompt: string;
  notes?: string;
  settings?: PromptSettings;
}
export interface DiffLine {
  op: "equal" | "insert" | "delete";
  old_line: number | null;
  new_line: number | null;
  text: string;
}
export interface TextDiff {
  changed: boolean;
  added: number;
  removed: number;
  unified: string;
  lines: DiffLine[];
}
export interface VersionDiff {
  prompt_id: ID;
  from_version: number;
  to_version: number;
  system: TextDiff;
  prompt: TextDiff;
  settings_changed: boolean;
  settings_from: PromptSettings;
  settings_to: PromptSettings;
  notes_from: string;
  notes_to: string;
}
export interface TagCount {
  tag: string;
  count: number;
}
export interface TagsResponse {
  tags: TagCount[];
}

// ---------- compare ----------
export interface CompareVariantInput {
  label?: string | null;
  system?: string | null;
  prompt: string;
  prompt_version_id?: ID | null;
}
export interface CompareRequest {
  variants: CompareVariantInput[];
  models: string[];
  variables?: Record<string, string>;
  temperature?: number | null;
  max_tokens?: number | null;
  thinking?: boolean;
  timeout_seconds?: number | null;
  save_history?: boolean;
}
export interface CompareVariant {
  index: number;
  label: string;
  system: string | null;
  prompt: string;
  prompt_version_id: ID | null;
}
export interface CompareCellRef {
  index: number;
  variant_index: number;
  model: string;
  provider: ProviderId;
}
export interface CompareCell extends CompareCellRef {
  variant_label: string;
  status: "ok" | "error";
  result: RunResult | null;
  error: ErrorBody | null;
}
export interface CompareSummary {
  ok_count: number;
  error_count: number;
  fastest_cell: number | null;
  cheapest_cell: number | null;
}
export interface CompareResult {
  id: ID;
  created_at: Timestamp;
  variants: CompareVariant[];
  models: string[];
  variables: Record<string, string>;
  params: RunParams;
  cells: CompareCell[];
  summary: CompareSummary;
  warnings: string[];
}
// SSE payloads for POST /api/compare/stream
export interface CompareStartEvent {
  comparison_id: ID;
  created_at: Timestamp;
  cells: CompareCellRef[];
  warnings: string[];
}
export type CompareCellEvent = CompareCell;
export type CompareDoneEvent = CompareResult;
export type CompareErrorEvent = ErrorEnvelope;

// ---------- test suites ----------
export type Assertion =
  | { type: "contains"; value: string; case_sensitive: boolean }
  | { type: "not_contains"; value: string; case_sensitive: boolean }
  | { type: "equals"; value: string; case_sensitive: boolean; trim: boolean }
  | { type: "starts_with"; value: string; case_sensitive: boolean; trim: boolean }
  | { type: "regex"; pattern: string; flags: string }
  | { type: "max_chars"; value: number }
  | { type: "min_chars"; value: number }
  | { type: "json_valid" }
  | { type: "json_schema"; schema: Record<string, unknown> }
  | { type: "llm_judge"; rubric: string; threshold: number; judge_model: string | null };
export type AssertionType = Assertion["type"];

export interface CaseInput {
  name: string;
  variables?: Record<string, string>;
  assertions: Assertion[];
}
export interface TestCase {
  id: ID;
  suite_id: ID;
  name: string;
  variables: Record<string, string>;
  assertions: Assertion[];
  position: number;
  created_at: Timestamp;
  updated_at: Timestamp;
}
export type EvalStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export interface SuiteSummary {
  id: ID;
  name: string;
  description: string;
  case_count: number;
  created_at: Timestamp;
  updated_at: Timestamp;
  last_eval: { id: ID; status: EvalStatus; pass_rate: number | null; created_at: Timestamp } | null;
}
export interface SuiteDetail extends SuiteSummary {
  cases: TestCase[];
}
export interface SuiteCreate {
  name: string;
  description?: string;
  cases?: CaseInput[];
}
export interface SuiteUpdate {
  name?: string;
  description?: string;
}

// ---------- evaluations ----------
export type CaseResultStatus = "pending" | "passed" | "failed" | "error";
export interface AssertionResult {
  type: Assertion["type"];
  passed: boolean;
  score: number | null;
  detail: string;
  error: string | null;
}
export interface EvalCreate {
  suite_id: ID;
  prompt_version_id?: ID | null;
  system?: string | null;
  prompt?: string | null;
  models: string[];
  temperature?: number | null;
  max_tokens?: number | null;
  thinking?: boolean;
  judge_model?: string | null;
}
export interface EvalProgress {
  completed: number;
  total: number;
}
export interface EvalRunSummary {
  id: ID;
  suite_id: ID | null;
  suite_name: string;
  prompt_id: ID | null;
  prompt_version_id: ID | null;
  prompt_label: string;
  models: string[];
  status: EvalStatus;
  progress: EvalProgress;
  passed: number;
  failed: number;
  errored: number;
  pass_rate: number | null;
  created_at: Timestamp;
  started_at: Timestamp | null;
  finished_at: Timestamp | null;
  error: ErrorBody | null;
}
export interface EvalCaseSnapshot {
  index: number;
  case_id: ID | null;
  name: string;
  variables: Record<string, string>;
  assertions: Assertion[];
}
export interface EvalResult {
  id: ID;
  case_index: number;
  case_id: ID | null;
  case_name: string;
  model: string;
  provider: ProviderId;
  status: CaseResultStatus;
  output: string | null;
  assertions: AssertionResult[];
  score: number | null;
  latency_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  error: ErrorBody | null;
}
export interface EvalModelSummary {
  model: string;
  provider: ProviderId;
  passed: number;
  failed: number;
  errored: number;
  pending: number;
  pass_rate: number | null;
  avg_latency_ms: number | null;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number | null;
}
export interface EvalRunDetail extends EvalRunSummary {
  system: string | null;
  prompt: string;
  params: RunParams;
  judge_model: string;
  cases: EvalCaseSnapshot[];
  results: EvalResult[];
  per_model: EvalModelSummary[];
}

// ---------- history ----------
export type HistoryStatus = "success" | "error" | "cancelled";
export type HistorySource = "run" | "compare";
export interface HistorySummary {
  id: ID;
  created_at: Timestamp;
  source: HistorySource;
  group_id: ID | null;
  model: string;
  provider: ProviderId;
  status: HistoryStatus;
  prompt_preview: string;
  output_preview: string;
  input_tokens: number | null;
  output_tokens: number | null;
  latency_ms: number | null;
  cost_usd: number | null;
  finish_reason: FinishReason | null;
  error_code: string | null;
  prompt_version_id: ID | null;
}
export interface HistoryDetail extends HistorySummary {
  system_template: string | null;
  prompt_template: string;
  variables: Record<string, string>;
  rendered_system: string | null;
  rendered_prompt: string;
  params: RunParams;
  output: string;
  thinking: string | null;
  error_message: string | null;
  ttft_ms: number | null;
  request_id: string | null;
  warnings: string[];
}
export interface DeletedCount {
  deleted: number;
}

// ---------- export / import ----------
export interface ExportVersion {
  id: ID;
  version: number;
  system: string | null;
  prompt: string;
  notes: string;
  settings: PromptSettings;
  created_at: Timestamp;
}
export interface ExportPrompt {
  id: ID;
  name: string;
  description: string;
  tags: string[];
  archived: boolean;
  created_at: Timestamp;
  updated_at: Timestamp;
  versions: ExportVersion[];
}
export interface ExportCase {
  id: ID;
  name: string;
  variables: Record<string, string>;
  assertions: Assertion[];
  position: number;
  created_at: Timestamp;
  updated_at: Timestamp;
}
export interface ExportSuite {
  id: ID;
  name: string;
  description: string;
  created_at: Timestamp;
  updated_at: Timestamp;
  cases: ExportCase[];
}
export interface ExportDocument {
  format: "prompt-studio-export";
  format_version: 1;
  exported_at: Timestamp;
  app_version: string;
  prompts: ExportPrompt[];
  suites: ExportSuite[];
  history: HistoryDetail[];
}
export interface ImportCounts {
  created: number;
  updated: number;
  skipped: number;
  renamed: number;
}
export interface ImportResult {
  prompts: ImportCounts;
  suites: ImportCounts;
  history: { created: number };
  warnings: string[];
}
