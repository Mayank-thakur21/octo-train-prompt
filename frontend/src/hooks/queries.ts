/** Shared queries for catalog data used across pages. */
import { useQuery } from "@tanstack/react-query";
import { getMeta, getModels, getReady, getTemplates } from "../api/endpoints";
import { CATALOG_STALE_TIME } from "../api/queryClient";
import { queryKeys } from "../api/queryKeys";

/** Server metadata (limits, providers, demo mode). Public endpoint. */
export function useMeta() {
  return useQuery({
    queryKey: queryKeys.meta(),
    queryFn: ({ signal }) => getMeta(signal),
    staleTime: CATALOG_STALE_TIME,
  });
}

/** Model catalog with availability. */
export function useModels() {
  return useQuery({
    queryKey: queryKeys.models(),
    queryFn: ({ signal }) => getModels(signal),
    staleTime: CATALOG_STALE_TIME,
  });
}

/** Built-in templates. */
export function useTemplates(enabled = true) {
  return useQuery({
    queryKey: queryKeys.templates(),
    queryFn: ({ signal }) => getTemplates(signal),
    staleTime: CATALOG_STALE_TIME,
    enabled,
  });
}

/** Backend readiness, polled every 30 s for the Online/Offline indicator. */
export function useReady() {
  return useQuery({
    queryKey: queryKeys.ready(),
    queryFn: ({ signal }) => getReady(signal),
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    retry: false,
    meta: { silent: true },
  });
}
