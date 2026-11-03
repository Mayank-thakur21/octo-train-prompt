import { afterEach, describe, expect, it, vi } from "vitest";
import { copyText } from "./clipboard";

const original = Object.getOwnPropertyDescriptor(window.navigator, "clipboard");

function setClipboard(value: unknown) {
  Object.defineProperty(window.navigator, "clipboard", { value, configurable: true });
}

afterEach(() => {
  if (original) Object.defineProperty(window.navigator, "clipboard", original);
  else Reflect.deleteProperty(window.navigator, "clipboard");
  Reflect.deleteProperty(document, "execCommand");
});

describe("copyText", () => {
  it("uses the async clipboard API when it exists", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    setClipboard({ writeText });
    expect(await copyText("hello")).toBe(true);
    expect(writeText).toHaveBeenCalledWith("hello");
  });

  it("falls back to a selected textarea outside secure contexts (plain HTTP)", async () => {
    setClipboard(undefined);
    let copied = "";
    const execCommand = vi.fn((command: string) => {
      const active = document.activeElement;
      if (command === "copy" && active instanceof HTMLTextAreaElement) copied = active.value;
      return true;
    });
    Object.defineProperty(document, "execCommand", { value: execCommand, configurable: true });
    const button = document.createElement("button");
    document.body.append(button);
    button.focus();

    expect(await copyText("over http")).toBe(true);
    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(copied).toBe("over http");
    // The helper textarea is removed and focus goes back.
    expect(document.querySelector("textarea")).toBeNull();
    expect(button).toHaveFocus();
    button.remove();
  });

  it("falls back when the async API rejects, and reports a total failure", async () => {
    setClipboard({ writeText: () => Promise.reject(new Error("denied")) });
    Object.defineProperty(document, "execCommand", { value: () => false, configurable: true });
    expect(await copyText("x")).toBe(false);
  });
});
