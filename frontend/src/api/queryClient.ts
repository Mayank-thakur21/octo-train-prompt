/** QueryClient factory with the app-wide retry and error policy (contract section 8.3). */
import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { toastForError, type ToastInput } from "../context/toast";
import { ApiError } from "./client";

declare module "@tanstack/react-query" {
  interface Register {
    queryMeta: {
      /** Skip the global error toast (background polling, token estimates). */
      silent?: boolean;
    };
    mutationMeta: {
      silent?: boolean;
    };
  }
}

/** Retries only network failures and 5xx responses, at most twice. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= 2) return false;
  return error instanceof ApiError && (error.code === "network_error" || error.status >= 500);
}

/** Cache time for slow-changing catalog data (meta, models, templates). */
export const CATALOG_STALE_TIME = 30_000;

/** Builds the app QueryClient; global errors (401, 429, offline) are reported through `notify`. */
export function createQueryClient(notify: (toast: ToastInput) => void): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (query.meta?.silent) return;
        const toast = toastForError(error);
        if (toast) notify(toast);
      },
    }),
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        if (mutation.meta?.silent) return;
        const toast = toastForError(error);
        if (toast) notify(toast);
      },
    }),
    defaultOptions: {
      queries: {
        retry: shouldRetry,
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}
