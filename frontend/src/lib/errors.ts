/** Human-readable messages for API errors. Only envelope fields are shown, never raw bodies. */
import { ApiError } from "../api/client";
import { isRecord } from "./storage";

/** Short message for any thrown value. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return "Something went wrong.";
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

/** Extra explanation lines derived from `error.details` (missing variables, validation errors, limits...). */
export function errorDetailLines(error: unknown): string[] {
  if (!(error instanceof ApiError) || !error.details) return [];
  const details = error.details;
  const lines: string[] = [];

  const missing = stringList(details.missing);
  if (missing.length > 0) lines.push(`Missing variables: ${missing.join(", ")}`);

  if (Array.isArray(details.cases)) {
    for (const item of details.cases) {
      if (!isRecord(item)) continue;
      const name = typeof item.case_name === "string" ? item.case_name : "Case";
      const names = stringList(item.missing);
      if (names.length > 0) lines.push(`${name}: missing ${names.join(", ")}`);
    }
  }

  if (Array.isArray(details.errors)) {
    for (const item of details.errors) {
      if (!isRecord(item) || typeof item.msg !== "string") continue;
      const loc = Array.isArray(item.loc)
        ? item.loc
            .filter((part): part is string | number => typeof part === "string" || typeof part === "number")
            .filter((part, index) => !(index === 0 && (part === "body" || part === "query" || part === "path")))
            .join(".")
        : "";
      lines.push(loc ? `${loc}: ${item.msg}` : item.msg);
    }
  }

  if (typeof details.reason === "string") {
    const where: string[] = [];
    if (typeof details.suite_index === "number") where.push(`suite ${details.suite_index + 1}`);
    if (typeof details.case_index === "number") where.push(`case ${details.case_index + 1}`);
    if (typeof details.assertion_index === "number") where.push(`assertion ${details.assertion_index + 1}`);
    lines.push(where.length > 0 ? `${where.join(", ")}: ${details.reason}` : details.reason);
  }

  if (typeof details.param === "string") {
    lines.push(
      typeof details.max === "number" ? `Parameter ${details.param} (maximum ${details.max})` : `Parameter ${details.param}`,
    );
  } else if (typeof details.limit === "string" && typeof details.max === "number") {
    lines.push(`Limit ${details.limit}: maximum ${details.max}`);
  }

  if (typeof details.request_id === "string") lines.push(`Request ID: ${details.request_id}`);

  return [...new Set(lines)];
}
