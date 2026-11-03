import { afterEach, describe, expect, it, vi } from "vitest";
import { isStringRecord, readStorage, removeStorage, writeStorage } from "./storage";

describe("storage helpers", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("stores JSON and reads it back", () => {
    expect(writeStorage("k", { a: 1 })).toBe(true);
    expect(window.localStorage.getItem("k")).toBe('{"a":1}');
    expect(readStorage("k", null)).toEqual({ a: 1 });
    removeStorage("k");
    expect(readStorage("k", "fallback")).toBe("fallback");
  });

  it("falls back on corrupted JSON or a failed guard", () => {
    window.localStorage.setItem("bad", "{not json");
    expect(readStorage("bad", 7)).toBe(7);
    window.localStorage.setItem("num", "5");
    expect(readStorage("num", "x", (value): value is string => typeof value === "string")).toBe("x");
  });

  it("survives unavailable storage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readStorage("k", "fallback")).toBe("fallback");
    expect(writeStorage("k", 1)).toBe(false);
  });

  it("recognises string records", () => {
    expect(isStringRecord({ a: "1" })).toBe(true);
    expect(isStringRecord({ a: 1 })).toBe(false);
    expect(isStringRecord(["a"])).toBe(false);
  });
});
