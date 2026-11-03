import { describe, expect, it } from "vitest";
import {
  finishReasonLabel,
  formatBytes,
  formatCost,
  formatLatency,
  formatPercent,
  formatRelativeTime,
  formatTokens,
} from "./format";

describe("format helpers", () => {
  it("formats tokens with thousands separators", () => {
    expect(formatTokens(1234567)).toBe("1,234,567");
    expect(formatTokens(0)).toBe("0");
    expect(formatTokens(null)).toBe("-");
  });

  it("formats latency in ms below one second and seconds above", () => {
    expect(formatLatency(830)).toBe("830 ms");
    expect(formatLatency(1234)).toBe("1.2 s");
    expect(formatLatency(null)).toBe("-");
  });

  it("formats cost with four decimals, a floor marker and a dash for null", () => {
    expect(formatCost(0.0042)).toBe("$0.0042");
    expect(formatCost(1.23456)).toBe("$1.2346");
    expect(formatCost(0.00001)).toBe("<$0.0001");
    expect(formatCost(0)).toBe("$0.0000");
    expect(formatCost(null)).toBe("-");
  });

  it("formats percentages", () => {
    expect(formatPercent(0.756)).toBe("76%");
    expect(formatPercent(null)).toBe("-");
  });

  it("formats relative times", () => {
    const now = Date.parse("2026-11-03T12:00:00Z");
    expect(formatRelativeTime("2026-11-03T11:59:50Z", now)).toBe("just now");
    expect(formatRelativeTime("2026-11-03T11:57:00Z", now)).toBe("3 min ago");
    expect(formatRelativeTime("2026-11-03T10:00:00Z", now)).toBe("2 h ago");
    expect(formatRelativeTime("2026-11-02T12:00:00Z", now)).toBe("1 day ago");
    expect(formatRelativeTime("2026-10-29T12:00:00Z", now)).toBe("5 days ago");
    expect(formatRelativeTime("not a date", now)).toBe("not a date");
  });

  it("formats byte sizes and finish reasons", () => {
    expect(formatBytes(2097152)).toBe("2 MiB");
    expect(formatBytes(1536)).toBe("1.5 KiB");
    expect(formatBytes(12)).toBe("12 B");
    expect(finishReasonLabel("length")).toBe("Max tokens reached");
    expect(finishReasonLabel("weird")).toBe("Other");
  });
});
