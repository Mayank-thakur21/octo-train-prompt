/** Display formatting for numbers, tokens, latency, cost and dates (contract section 8.5). */

const integerFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

/** Token counts with thousands separators; "-" for null. */
export function formatTokens(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : integerFormat.format(value);
}

/** Integers with thousands separators. */
export function formatNumber(value: number): string {
  return integerFormat.format(value);
}

/** `830 ms` below one second, otherwise `1.2 s`; "-" for null. */
export function formatLatency(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "-";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

/** `$0.0042` (4 decimals), `<$0.0001` for smaller non-zero values, "-" for null. */
export function formatCost(usd: number | null | undefined): string {
  if (usd === null || usd === undefined) return "-";
  if (usd > 0 && usd < 0.0001) return "<$0.0001";
  return `$${usd.toFixed(4)}`;
}

/** Fraction 0..1 as a whole percentage; "-" for null. */
export function formatPercent(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return "-";
  return `${Math.round(rate * 100)}%`;
}

/** Absolute local date and time, e.g. for `title` attributes. */
export function formatDateTime(timestamp: string): string {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return timestamp;
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
}

/** Relative time such as "just now", "3 min ago", "2 h ago" or "5 days ago"; older dates are absolute. */
export function formatRelativeTime(timestamp: string, now: number = Date.now()): string {
  const time = new Date(timestamp).getTime();
  if (Number.isNaN(time)) return timestamp;
  const seconds = Math.round((now - time) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${Math.max(1, minutes)} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return days === 1 ? "1 day ago" : `${days} days ago`;
  return new Date(time).toLocaleDateString(undefined, { dateStyle: "medium" });
}

/** Byte sizes for limits, e.g. `2 MiB`. */
export function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${+(bytes / (1024 * 1024)).toFixed(1)} MiB`;
  if (bytes >= 1024) return `${+(bytes / 1024).toFixed(1)} KiB`;
  return `${bytes} B`;
}

/** Human label for a finish reason. */
export function finishReasonLabel(reason: string): string {
  switch (reason) {
    case "stop":
      return "Completed";
    case "length":
      return "Max tokens reached";
    case "content_filter":
      return "Content filtered";
    case "refusal":
      return "Refused";
    default:
      return "Other";
  }
}

/** Provider group labels used by the model pickers. */
export const PROVIDER_LABELS: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  gemini: "Google Gemini",
  demo: "Demo (offline)",
};
