/** Sample API payloads shaped exactly like the contract (section 2.4). */
import type {
  EvalRunDetail,
  HistoryDetail,
  HistorySummary,
  Meta,
  ModelInfo,
  ModelsResponse,
  Page,
  PromptDetail,
  PromptSummary,
  RunResult,
  SuiteDetail,
  VersionDetail,
  VersionDiff,
} from "../api/types";
import { json, route, type MockRoute } from "./fetchMock";

export const ID = {
  prompt: "a".repeat(32),
  version1: "b".repeat(32),
  version2: "c".repeat(32),
  history: "d".repeat(32),
  suite: "e".repeat(32),
  case1: "f".repeat(32),
  eval: "1".repeat(32),
  run: "2".repeat(32),
  comparison: "3".repeat(32),
};

export const NOW = "2026-11-03T09:15:02.123456Z";

const base: Omit<ModelInfo, "id" | "provider" | "display_name"> = {
  available: true,
  is_default: false,
  supports_thinking: true,
  thinking_always_on: false,
  supports_temperature: true,
  max_output_tokens: 4096,
  context_window: null,
  pricing: null,
};

export const MODELS: ModelInfo[] = [
  {
    ...base,
    id: "claude-opus-5-5",
    provider: "anthropic",
    display_name: "Claude Opus 5.5",
    available: true,
    is_default: true,
    thinking_always_on: true,
    supports_temperature: false,
    max_output_tokens: 16384,
    context_window: 1000000,
    pricing: { currency: "USD", input_per_mtok: 4, output_per_mtok: 20, long_context: null },
  },
  {
    ...base,
    id: "claude-haiku-5-5",
    provider: "anthropic",
    display_name: "Claude Haiku 5.5",
    available: false,
    supports_temperature: false,
    max_output_tokens: 16384,
    context_window: 1000000,
  },
  {
    ...base,
    id: "gpt-5.5",
    provider: "openai",
    display_name: "GPT-5.5",
    available: false,
    supports_thinking: false,
    supports_temperature: false,
    max_output_tokens: 16384,
  },
  { ...base, id: "gemini-3.5-flash", provider: "gemini", display_name: "Gemini 3.5 Flash", available: false },
  { ...base, id: "demo-concise", provider: "demo", display_name: "Demo Concise (offline)" },
  { ...base, id: "demo-verbose", provider: "demo", display_name: "Demo Verbose (offline)" },
];

export const MODELS_RESPONSE: ModelsResponse = { models: MODELS, default_model: "claude-opus-5-5" };

export const META: Meta = {
  name: "Prompt Engineering Studio",
  version: "2.0.0",
  auth_required: false,
  demo_mode: false,
  default_model: "claude-opus-5-5",
  providers: [
    { id: "anthropic", display_name: "Anthropic", configured: true },
    { id: "openai", display_name: "OpenAI", configured: false },
    { id: "gemini", display_name: "Google Gemini", configured: false },
    { id: "demo", display_name: "Demo", configured: true },
  ],
  limits: {
    max_prompt_chars: 100000,
    max_system_chars: 50000,
    max_rendered_chars: 200000,
    max_variables: 50,
    max_variable_value_chars: 50000,
    max_output_tokens: 16384,
    default_max_tokens: 4096,
    max_compare_variants: 4,
    max_compare_models: 4,
    max_compare_cells: 12,
    max_cases_per_suite: 100,
    max_assertions_per_case: 20,
    max_eval_models: 4,
    max_eval_calls: 200,
    max_tags_per_prompt: 10,
    max_versions_per_prompt: 200,
    max_body_bytes: 2097152,
    import_max_bytes: 5242880,
    request_timeout_seconds: 120,
  },
};

export function runResult(overrides: Partial<RunResult> = {}): RunResult {
  return {
    id: ID.run,
    created_at: NOW,
    model: "claude-opus-5-5",
    provider: "anthropic",
    text: "Hello world",
    thinking: null,
    input_tokens: 12,
    output_tokens: 34,
    latency_ms: 1234,
    ttft_ms: 210,
    finish_reason: "stop",
    request_id: "req_1",
    cost_usd: 0.0042,
    warnings: [],
    rendered_system: null,
    rendered_prompt: "Hello",
    params: { temperature: null, max_tokens: 4096, thinking: false },
    ...overrides,
  };
}

export function versionDetail(version: number, overrides: Partial<VersionDetail> = {}): VersionDetail {
  return {
    id: version === 1 ? ID.version1 : ID.version2,
    prompt_id: ID.prompt,
    version,
    system: "You are helpful.",
    prompt: version === 1 ? "Summarize {{text}}" : "Summarize {{text}} in {{count|3}} bullets",
    notes: version === 1 ? "" : "Added count",
    settings: { model: "claude-opus-5-5", temperature: null, max_tokens: 1024, thinking: false },
    variables: [{ name: "text", default: null, required: true }],
    created_at: NOW,
    ...overrides,
  };
}

export function promptDetail(overrides: Partial<PromptDetail> = {}): PromptDetail {
  return {
    id: ID.prompt,
    name: "Summarizer",
    description: "Summaries in bullets",
    tags: ["writing"],
    archived: false,
    created_at: NOW,
    updated_at: NOW,
    version_count: 2,
    latest_version: versionDetail(2),
    ...overrides,
  };
}

export function promptSummary(overrides: Partial<PromptSummary> = {}): PromptSummary {
  const detail = promptDetail();
  return {
    id: detail.id,
    name: detail.name,
    description: detail.description,
    tags: detail.tags,
    archived: false,
    created_at: NOW,
    updated_at: NOW,
    version_count: 2,
    latest_version: {
      id: ID.version2,
      prompt_id: ID.prompt,
      version: 2,
      notes: "Added count",
      created_at: NOW,
      variables: ["text", "count"],
    },
    ...overrides,
  };
}

export function page<T>(items: T[], total = items.length, limit = 20, offset = 0): Page<T> {
  return { items, total, limit, offset };
}

export const VERSION_DIFF: VersionDiff = {
  prompt_id: ID.prompt,
  from_version: 1,
  to_version: 2,
  system: { changed: false, added: 0, removed: 0, unified: "", lines: [{ op: "equal", old_line: 1, new_line: 1, text: "You are helpful." }] },
  prompt: {
    changed: true,
    added: 1,
    removed: 1,
    unified: "--- v1\n+++ v2\n@@ -1 +1 @@\n-Summarize {{text}}\n+Summarize {{text}} in {{count|3}} bullets",
    lines: [
      { op: "delete", old_line: 1, new_line: null, text: "Summarize {{text}}" },
      { op: "insert", old_line: null, new_line: 1, text: "Summarize {{text}} in {{count|3}} bullets" },
    ],
  },
  settings_changed: false,
  settings_from: { model: "claude-opus-5-5", temperature: null, max_tokens: 1024, thinking: false },
  settings_to: { model: "claude-opus-5-5", temperature: null, max_tokens: 1024, thinking: false },
  notes_from: "",
  notes_to: "Added count",
};

export function historySummary(overrides: Partial<HistorySummary> = {}): HistorySummary {
  return {
    id: ID.history,
    created_at: NOW,
    source: "run",
    group_id: null,
    model: "demo-concise",
    provider: "demo",
    status: "success",
    prompt_preview: "Hello Ada",
    output_preview: "Hi there",
    input_tokens: 3,
    output_tokens: 5,
    latency_ms: 120,
    cost_usd: null,
    finish_reason: "stop",
    error_code: null,
    prompt_version_id: null,
    ...overrides,
  };
}

export function historyDetail(overrides: Partial<HistoryDetail> = {}): HistoryDetail {
  return {
    ...historySummary(),
    system_template: "Be brief.",
    prompt_template: "Hello {{name}}",
    variables: { name: "Ada" },
    rendered_system: "Be brief.",
    rendered_prompt: "Hello Ada",
    params: { temperature: 0.7, max_tokens: 512, thinking: false },
    output: "Hi there",
    thinking: null,
    error_message: null,
    ttft_ms: 40,
    request_id: "demo_abc",
    warnings: [],
    ...overrides,
  };
}

export function suiteDetail(overrides: Partial<SuiteDetail> = {}): SuiteDetail {
  return {
    id: ID.suite,
    name: "Greeting suite",
    description: "Checks greetings",
    case_count: 1,
    created_at: NOW,
    updated_at: NOW,
    last_eval: null,
    cases: [
      {
        id: ID.case1,
        suite_id: ID.suite,
        name: "Says hello",
        variables: { name: "Ada" },
        assertions: [{ type: "contains", value: "hello", case_sensitive: false }],
        position: 1,
        created_at: NOW,
        updated_at: NOW,
      },
    ],
    ...overrides,
  };
}

export function evalDetail(overrides: Partial<EvalRunDetail> = {}): EvalRunDetail {
  return {
    id: ID.eval,
    suite_id: ID.suite,
    suite_name: "Greeting suite",
    prompt_id: null,
    prompt_version_id: null,
    prompt_label: "Ad-hoc prompt",
    models: ["demo-concise"],
    status: "completed",
    progress: { completed: 1, total: 1 },
    passed: 1,
    failed: 0,
    errored: 0,
    pass_rate: 1,
    created_at: NOW,
    started_at: NOW,
    finished_at: NOW,
    error: null,
    system: null,
    prompt: "Say hello to {{name}}",
    params: { temperature: null, max_tokens: 1024, thinking: false },
    judge_model: "demo-concise",
    cases: [
      {
        index: 0,
        case_id: ID.case1,
        name: "Says hello",
        variables: { name: "Ada" },
        assertions: [{ type: "contains", value: "hello", case_sensitive: false }],
      },
    ],
    results: [
      {
        id: "9".repeat(32),
        case_index: 0,
        case_id: ID.case1,
        case_name: "Says hello",
        model: "demo-concise",
        provider: "demo",
        status: "passed",
        output: "Hello Ada!",
        assertions: [{ type: "contains", passed: true, score: null, detail: 'Output contains "hello".', error: null }],
        score: 1,
        latency_ms: 90,
        input_tokens: 5,
        output_tokens: 3,
        cost_usd: null,
        error: null,
      },
    ],
    per_model: [
      {
        model: "demo-concise",
        provider: "demo",
        passed: 1,
        failed: 0,
        errored: 0,
        pending: 0,
        pass_rate: 1,
        avg_latency_ms: 90,
        total_input_tokens: 5,
        total_output_tokens: 3,
        total_cost_usd: null,
      },
    ],
    ...overrides,
  };
}

/** Routes every page needs (meta, models, readiness, templates). */
export function catalogRoutes(): MockRoute[] {
  return [
    route("GET", "/api/meta", META),
    route("GET", "/api/models", MODELS_RESPONSE),
    route("GET", "/api/ready", { status: "ready", checks: { database: "ok" } }),
    route("GET", "/api/templates", {
      templates: [
        {
          id: "summarizer",
          name: "Summarizer",
          description: "Summarizes text in three bullet points.",
          tags: ["writing"],
          system: "You are a concise summarizer.",
          prompt: "Summarize the following text in 3 bullet points:\n\n{{text}}",
          variables: [{ name: "text", default: null, required: true }],
        },
      ],
    }),
    route("POST", "/api/tokens/estimate", () =>
      json({
        model: "claude-opus-5-5",
        provider: "anthropic",
        input_tokens: 42,
        method: "anthropic_count_tokens",
        characters: 160,
        words: 30,
        warnings: [],
      }),
    ),
  ];
}
