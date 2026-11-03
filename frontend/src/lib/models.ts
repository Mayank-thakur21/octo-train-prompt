/** Helpers for the model catalog. */
import type { Limits, ModelInfo, ProviderId } from "../api/types";
import { PROVIDER_LABELS } from "./format";

export interface ModelGroup {
  provider: ProviderId;
  label: string;
  models: ModelInfo[];
}

/** Groups models by provider, keeping catalog order (Anthropic, OpenAI, Gemini, Demo). */
export function groupModels(models: readonly ModelInfo[]): ModelGroup[] {
  const groups = new Map<ProviderId, ModelGroup>();
  for (const model of models) {
    let group = groups.get(model.provider);
    if (!group) {
      group = { provider: model.provider, label: PROVIDER_LABELS[model.provider] ?? model.provider, models: [] };
      groups.set(model.provider, group);
    }
    group.models.push(model);
  }
  return [...groups.values()];
}

/** Finds a model by id. */
export function findModel(models: readonly ModelInfo[] | undefined, id: string | null | undefined): ModelInfo | undefined {
  if (!models || !id) return undefined;
  return models.find((model) => model.id === id);
}

/** Display name for a model id (falls back to the id itself). */
export function modelName(models: readonly ModelInfo[] | undefined, id: string): string {
  return findModel(models, id)?.display_name ?? id;
}

/** Default `max_tokens` for a model: min(DEFAULT_MAX_TOKENS, model max). */
export function defaultMaxTokens(limits: Limits | undefined, model: ModelInfo | undefined): number {
  const fallback = limits?.default_max_tokens ?? 4096;
  return model ? Math.min(fallback, model.max_output_tokens) : fallback;
}

/** Capabilities shared by several selected models (compare and evals). */
export interface CombinedCapabilities {
  supportsTemperature: boolean;
  supportsThinking: boolean;
  thinkingAlwaysOn: boolean;
  maxOutputTokens: number;
}

/** Combines capabilities: features are offered when at least one model supports them. */
export function combineCapabilities(models: readonly ModelInfo[], fallbackMax: number): CombinedCapabilities {
  if (models.length === 0) {
    return { supportsTemperature: true, supportsThinking: true, thinkingAlwaysOn: false, maxOutputTokens: fallbackMax };
  }
  return {
    supportsTemperature: models.some((model) => model.supports_temperature),
    supportsThinking: models.some((model) => model.supports_thinking),
    thinkingAlwaysOn: models.every((model) => model.thinking_always_on),
    maxOutputTokens: Math.min(...models.map((model) => model.max_output_tokens)),
  };
}
