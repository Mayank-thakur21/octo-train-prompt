/**
 * TanStack Query keys (contract section 8.3). Mutations invalidate by prefix,
 * e.g. `["prompts"]` refreshes every prompt list regardless of its filters.
 */
import type { EvalListParams, HistoryListParams, PageParams, PromptListParams, SuiteListParams } from "./endpoints";
import type { ID, TokenEstimateRequest } from "./types";

export const queryKeys = {
  ready: () => ["ready"] as const,
  meta: () => ["meta"] as const,
  models: () => ["models"] as const,
  templates: () => ["templates"] as const,
  tokens: (req: TokenEstimateRequest) => ["tokens", req] as const,
  prompts: (params?: PromptListParams) => (params ? (["prompts", params] as const) : (["prompts"] as const)),
  prompt: (promptId: ID) => ["prompt", promptId] as const,
  versions: (promptId: ID, params?: PageParams) =>
    params ? (["versions", promptId, params] as const) : (["versions", promptId] as const),
  version: (promptId: ID, version: number) => ["version", promptId, version] as const,
  diff: (promptId: ID, from: number, to: number) => ["diff", promptId, from, to] as const,
  tags: () => ["tags"] as const,
  suites: (params?: SuiteListParams) => (params ? (["suites", params] as const) : (["suites"] as const)),
  suite: (suiteId: ID) => ["suite", suiteId] as const,
  evals: (params?: EvalListParams) => (params ? (["evals", params] as const) : (["evals"] as const)),
  eval: (evalId: ID) => ["eval", evalId] as const,
  history: (params?: HistoryListParams) => (params ? (["history", params] as const) : (["history"] as const)),
  historyItem: (historyId: ID) => ["historyItem", historyId] as const,
};
