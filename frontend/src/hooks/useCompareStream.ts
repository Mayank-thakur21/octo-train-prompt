import { useCallback, useEffect, useReducer, useRef } from "react";
import { ApiError, isAbortError } from "../api/client";
import { streamCompare } from "../api/endpoints";
import type { CompareCell, CompareRequest, CompareResult, CompareStartEvent } from "../api/types";
import type { StreamPhase } from "./useRunStream";

export interface CompareStreamState {
  phase: StreamPhase;
  start: CompareStartEvent | null;
  /** Finished cells keyed by cell index. */
  cells: Record<number, CompareCell>;
  result: CompareResult | null;
  error: ApiError | null;
}

export type CompareOutcome =
  | { status: "done"; result: CompareResult }
  | { status: "error"; error: ApiError }
  | { status: "stopped" };

type Action =
  | { type: "begin" }
  | { type: "start"; event: CompareStartEvent }
  | { type: "cell"; cell: CompareCell }
  | { type: "done"; result: CompareResult }
  | { type: "error"; error: ApiError }
  | { type: "stopped" };

const INITIAL: CompareStreamState = { phase: "idle", start: null, cells: {}, result: null, error: null };

function reducer(state: CompareStreamState, action: Action): CompareStreamState {
  switch (action.type) {
    case "begin":
      return { ...INITIAL, phase: "streaming" };
    case "start":
      return { ...state, start: action.event };
    case "cell":
      return { ...state, cells: { ...state.cells, [action.cell.index]: action.cell } };
    case "done": {
      const cells: Record<number, CompareCell> = {};
      for (const cell of action.result.cells) cells[cell.index] = cell;
      return { ...state, phase: "done", result: action.result, cells };
    }
    case "error":
      return { ...state, phase: "error", error: action.error };
    case "stopped":
      return { ...state, phase: "stopped" };
  }
}

/** Runs `POST /api/compare/stream`; cells fill in as their `cell` events arrive. */
export function useCompareStream() {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const controllerRef = useRef<AbortController | null>(null);

  const run = useCallback(async (req: CompareRequest): Promise<CompareOutcome> => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    dispatch({ type: "begin" });
    const isCurrent = () => controllerRef.current === controller;
    try {
      const result = await streamCompare(
        req,
        {
          onStart: (event) => {
            if (isCurrent()) dispatch({ type: "start", event });
          },
          onCell: (cell) => {
            if (isCurrent()) dispatch({ type: "cell", cell });
          },
        },
        controller.signal,
      );
      if (isCurrent()) dispatch({ type: "done", result });
      return { status: "done", result };
    } catch (error) {
      if (controller.signal.aborted || isAbortError(error)) {
        if (isCurrent()) dispatch({ type: "stopped" });
        return { status: "stopped" };
      }
      const apiError =
        error instanceof ApiError ? error : new ApiError(0, "internal_error", "Unexpected error while streaming.");
      if (isCurrent()) dispatch({ type: "error", error: apiError });
      return { status: "error", error: apiError };
    } finally {
      if (isCurrent()) controllerRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    controllerRef.current?.abort();
  }, []);

  useEffect(() => () => controllerRef.current?.abort(), []);

  return { ...state, isStreaming: state.phase === "streaming", run, stop };
}
