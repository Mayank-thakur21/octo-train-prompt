/** Global test setup: jest-dom matchers, DOM cleanup, storage/theme reset and browser API stubs. */
import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { installMatchMedia } from "./matchMedia";

// Pages are lazy-loaded, and on a busy CI runner the first import of a page chunk can take
// longer than Testing Library's 1 s default for findBy*/waitFor. Waiting longer only costs
// time when a test is already failing.
configure({ asyncUtilTimeout: 5000 });

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.className = "";
  document.documentElement.removeAttribute("style");
  document.title = "";
  installMatchMedia(false);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
