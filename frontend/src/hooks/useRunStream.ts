import { useCallback, useEffect, useReducer, useRef } from "react";
import { ApiError, isAbortError } from "../api/client";
import { streamRun } from "../api/endpoints";
import type { RunRequest, RunResult, RunStartEvent } from "../api/types";

export type StreamPhase = "idle" | "streaming" | "done" | "error" | "stopped";

export interface RunStreamState {
  phase: StreamPhase;
  start: RunStartEvent | null;
  /** Visible output so far (also kept after Stop or an error). */
  text: string;
  thinking: string;
  result: RunResult | null;
  error: ApiError | null;
}

export type RunOutcome =
  | { status: "done"; result: RunResult }
  | { status: "error"; error: ApiError }
  | { status: "stopped" };

type Action =
  | { type: "begin" }
  | { type: "start"; event: RunStartEvent }
  | { type: "append"; text: string; thinking: string }
  | { type: "done"; result: RunResult }
  | { type: "error"; error: ApiError }
  | { type: "stopped" };

const INITIAL: RunStreamState = { phase: "idle", start: null, text: "", thinking: "", result: null, error: null };

function reducer(state: RunStreamState, action: Action): RunStreamState {
  switch (action.type) {
    case "begin":
      return { ...INITIAL, phase: "streaming" };
    case "start":
      return { ...state, start: action.event };
    case "append":
      return { ...state, text: state.text + action.text, thinking: state.thinking + action.thinking };
    case "done":
      // The final text is authoritative (it equals the concatenated deltas).
      return {
        ...state,
        phase: "done",
        result: action.result,
        text: action.result.text,
        thinking: action.result.thinking ?? state.thinking,
      };
    case "error":
      return { ...state, phase: "error", error: action.error };
    case "stopped":
      return { ...state, phase: "stopped" };
  }
}

/** Schedules work for the next frame (falls back to a short timeout outside browsers). */
function nextFrame(callback: () => void): () => void {
  if (typeof window.requestAnimationFrame === "function") {
    const handle = window.requestAnimationFrame(callback);
    return () => window.cancelAnimationFrame(handle);
  }
  const handle = window.setTimeout(callback, 16);
  return () => window.clearTimeout(handle);
}

/**
 * Runs `POST /api/runs/stream` and exposes the live state. Deltas are batched
 * per animation frame. `stop()` aborts the fetch; the partial text is kept and
 * the phase becomes "stopped".
 */
export function useRunStream() {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const controllerRef = useRef<AbortController | null>(null);
  const bufferRef = useRef({ text: "", thinking: "" });
  const cancelFrameRef = useRef<(() => void) | null>(null);

  const flush = useCallback(() => {
    cancelFrameRef.current?.();
    cancelFrameRef.current = null;
    const { text, thinking } = bufferRef.current;
    if (!text && !thinking) return;
    bufferRef.current = { text: "", thinking: "" };
    dispatch({ type: "append", text, thinking });
  }, []);

  const run = useCallback(
    async (req: RunRequest): Promise<RunOutcome> => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      cancelFrameRef.current?.();
      cancelFrameRef.current = null;
      bufferRef.current = { text: "", thinking: "" };
      dispatch({ type: "begin" });
      const isCurrent = () => controllerRef.current === controller;
      try {
        const result = await streamRun(
          req,
          {
            onStart: (event) => {
              if (isCurrent()) dispatch({ type: "start", event });
            },
            onDelta: (delta) => {
              if (!isCurrent()) return;
              if (delta.type === "text") bufferRef.current.text += delta.text;
              else bufferRef.current.thinking += delta.text;
              cancelFrameRef.current ??= nextFrame(flush);
            },
          },
          controller.signal,
        );
        if (isCurrent()) {
          flush();
          dispatch({ type: "done", result });
        }
        return { status: "done", result };
      } catch (error) {
        if (controller.signal.aborted || isAbortError(error)) {
          if (isCurrent()) {
            flush();
            dispatch({ type: "stopped" });
          }
          return { status: "stopped" };
        }
        const apiError =
          error instanceof ApiError ? error : new ApiError(0, "internal_error", "Unexpected error while streaming.");
        if (isCurrent()) {
          flush();
          dispatch({ type: "error", error: apiError });
        }
        return { status: "error", error: apiError };
      } finally {
        if (isCurrent()) controllerRef.current = null;
      }
    },
    [flush],
  );

  const stop = useCallback(() => {
    controllerRef.current?.abort();
  }, []);

  // Abort an in-flight stream when the component unmounts.
  useEffect(
    () => () => {
      controllerRef.current?.abort();
      cancelFrameRef.current?.();
    },
    [],
  );

  return { ...state, isStreaming: state.phase === "streaming", run, stop };
}
