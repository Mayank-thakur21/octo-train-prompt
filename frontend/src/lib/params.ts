/** Run parameter state shared by the Playground, Compare and evaluation forms. */

export interface RunParamsValue {
  /** null = provider default ("Use model default"). */
  temperature: number | null;
  /** null = server default. */
  maxTokens: number | null;
  thinking: boolean;
}

/** True when the parameters can be sent (max tokens empty or a whole number within range). */
export function paramsAreValid(value: RunParamsValue, maxOutputTokens: number): boolean {
  return (
    value.maxTokens === null ||
    (Number.isInteger(value.maxTokens) && value.maxTokens >= 1 && value.maxTokens <= maxOutputTokens)
  );
}

/** Type guard for drafts restored from localStorage. */
export function isRunParamsValue(value: unknown): value is RunParamsValue {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    (record.temperature === null || typeof record.temperature === "number") &&
    (record.maxTokens === null || typeof record.maxTokens === "number") &&
    typeof record.thinking === "boolean"
  );
}
