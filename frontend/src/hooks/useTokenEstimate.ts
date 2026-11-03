import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { estimateTokens } from "../api/endpoints";
import { queryKeys } from "../api/queryKeys";
import type { TokenEstimateRequest } from "../api/types";
import { useDebouncedValue } from "./useDebouncedValue";

/** Debounce before asking the server for an estimate. */
export const TOKEN_ESTIMATE_DEBOUNCE_MS = 600;

/**
 * Debounced `POST /api/tokens/estimate`. Superseded requests are aborted
 * (TanStack Query cancels the signal when the key changes) and the previous
 * estimate stays visible while the next one loads.
 *
 * Callers build `request` inline, so it is a new object on every render. The
 * debounce therefore works on its JSON form: an identical request neither
 * restarts the timer nor counts as pending.
 */
export function useTokenEstimate(request: TokenEstimateRequest | null) {
  const serialized = request === null ? null : JSON.stringify(request);
  const debouncedSerialized = useDebouncedValue(serialized, TOKEN_ESTIMATE_DEBOUNCE_MS);
  const debounced = useMemo(
    () => (debouncedSerialized === null ? null : (JSON.parse(debouncedSerialized) as TokenEstimateRequest)),
    [debouncedSerialized],
  );
  const enabled = debounced !== null && debounced.prompt.length > 0;
  const query = useQuery({
    queryKey: queryKeys.tokens(debounced ?? { prompt: "" }),
    queryFn: ({ signal }) => estimateTokens(debounced ?? { prompt: "" }, signal),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    retry: false,
    meta: { silent: true },
  });
  return {
    estimate: enabled ? query.data : undefined,
    isPending: enabled && (query.isFetching || serialized !== debouncedSerialized),
    error: query.error,
  };
}
