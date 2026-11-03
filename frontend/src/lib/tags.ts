/** Splits a comma separated tag list into unique trimmed tags (the server normalises them further). */
export function parseTags(raw: string): string[] {
  return [...new Set(raw.split(",").map((tag) => tag.trim()).filter(Boolean))];
}
