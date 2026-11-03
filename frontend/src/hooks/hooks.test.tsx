import { QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import type { TokenEstimate } from "../api/types";
import { controlledSse, json, mockApi, route, sseFrame } from "../test/fetchMock";
import { ID, NOW, runResult } from "../test/fixtures";
import { createTestQueryClient } from "../test/utils";
import { useDebouncedValue } from "./useDebouncedValue";
import { useHotkey } from "./useHotkey";
import { useRunStream } from "./useRunStream";
import { useTokenEstimate } from "./useTokenEstimate";

describe("useRunStream", () => {
  it("accumulates deltas, then adopts the final result", async () => {
    const stream = controlledSse();
    mockApi([route("POST", "/api/runs/stream", () => stream.response)]);
    const { result } = renderHook(() => useRunStream());
    let outcome: Promise<unknown> = Promise.resolve();
    act(() => {
      outcome = result.current.run({ prompt: "x" });
    });
    expect(result.current.phase).toBe("streaming");
    stream.push(sseFrame("start", { run_id: ID.run, model: "m", provider: "demo", created_at: NOW, warnings: ["w"] }));
    stream.push(sseFrame("delta", { type: "thinking", text: "think " }) + sseFrame("delta", { type: "text", text: "Hi" }));
    await waitFor(() => expect(result.current.text).toBe("Hi"));
    expect(result.current.thinking).toBe("think ");
    expect(result.current.start?.warnings).toEqual(["w"]);

    stream.push(sseFrame("done", runResult({ text: "Hi!", thinking: "think" })));
    await act(async () => {
      await outcome;
    });
    expect(result.current.phase).toBe("done");
    expect(result.current.text).toBe("Hi!");
    expect(result.current.result?.latency_ms).toBe(1234);
  });

  it("stop() keeps the partial text and reports stopped", async () => {
    const stream = controlledSse();
    mockApi([route("POST", "/api/runs/stream", () => stream.response)]);
    const { result } = renderHook(() => useRunStream());
    let outcome: Promise<unknown> = Promise.resolve();
    act(() => {
      outcome = result.current.run({ prompt: "x" });
    });
    stream.push(sseFrame("start", { run_id: null }) + sseFrame("delta", { type: "text", text: "Part" }));
    await waitFor(() => expect(result.current.text).toBe("Part"));
    act(() => result.current.stop());
    await act(async () => {
      await expect(outcome).resolves.toEqual({ status: "stopped" });
    });
    expect(result.current.phase).toBe("stopped");
    expect(result.current.text).toBe("Part");
  });

  it("reports in-stream errors with the partial output", async () => {
    const stream = controlledSse();
    mockApi([route("POST", "/api/runs/stream", () => stream.response)]);
    const { result } = renderHook(() => useRunStream());
    let outcome: Promise<unknown> = Promise.resolve();
    act(() => {
      outcome = result.current.run({ prompt: "x" });
    });
    stream.push(sseFrame("start", { run_id: ID.run }) + sseFrame("delta", { type: "text", text: "Half" }));
    stream.push(sseFrame("error", { error: { code: "provider_overloaded", message: "Overloaded.", details: { run_id: ID.run } } }));
    await act(async () => {
      await outcome;
    });
    expect(result.current.phase).toBe("error");
    expect(result.current.error).toMatchObject({ code: "provider_overloaded", status: 503 });
    expect(result.current.text).toBe("Half");
  });
});

describe("useDebouncedValue", () => {
  it("only publishes the value after it settles", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, 300), { initialProps: { value: "a" } });
    rerender({ value: "ab" });
    rerender({ value: "abc" });
    expect(result.current).toBe("a");
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(result.current).toBe("abc");
  });
});

describe("useTokenEstimate", () => {
  function estimateFor(prompt: string): TokenEstimate {
    return {
      model: "demo-concise",
      provider: "demo",
      input_tokens: Math.ceil(prompt.length / 4),
      method: "heuristic",
      characters: prompt.length,
      words: prompt.split(/\s+/).length,
      warnings: [],
    };
  }

  it("settles for requests rebuilt on every render and refetches only when the content changes", async () => {
    const api = mockApi([
      route("POST", "/api/tokens/estimate", (request) => json(estimateFor((request.body as { prompt: string }).prompt))),
    ]);
    const client = createTestQueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    // The request object is created inline, exactly like the Playground does.
    const { result, rerender } = renderHook(
      ({ prompt }: { prompt: string }) => useTokenEstimate({ model: "demo-concise", system: null, prompt, variables: {} }),
      { initialProps: { prompt: "Hello there" }, wrapper },
    );
    await waitFor(() => expect(result.current.estimate?.characters).toBe(11), { timeout: 3000 });
    expect(result.current.isPending).toBe(false);

    // Same content in a new object: still settled, no new request.
    rerender({ prompt: "Hello there" });
    expect(result.current.isPending).toBe(false);
    await new Promise((resolve) => window.setTimeout(resolve, 700));
    expect(result.current.isPending).toBe(false);
    expect(api.callsTo("POST", "/api/tokens/estimate")).toHaveLength(1);

    // Changed content: pending until the debounced request answers.
    rerender({ prompt: "Hello there, friend" });
    expect(result.current.isPending).toBe(true);
    expect(result.current.estimate?.characters).toBe(11);
    await waitFor(() => expect(result.current.estimate?.characters).toBe(19), { timeout: 3000 });
    expect(result.current.isPending).toBe(false);
    expect(api.callsTo("POST", "/api/tokens/estimate")).toHaveLength(2);
  });
});

describe("useHotkey", () => {
  it("fires on Ctrl+Enter and Cmd+Enter only", () => {
    const handler = vi.fn();
    renderHook(() => useHotkey({ key: "Enter", mod: true }, handler));
    fireEvent.keyDown(window, { key: "Enter" });
    expect(handler).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "Enter", ctrlKey: true });
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    expect(handler).toHaveBeenCalledTimes(2);
  });
});
