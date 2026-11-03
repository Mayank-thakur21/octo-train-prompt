/** Toast notifications context and the global API error mapping (contract section 8.3). */
import { createContext, useContext } from "react";
import { ApiError } from "../api/client";

export type ToastTone = "success" | "error" | "info" | "warning";

export interface ToastInput {
  /** Reusing an id replaces the existing toast (used to de-duplicate global errors). */
  id?: string;
  tone: ToastTone;
  title: string;
  description?: string;
  /** Optional in-app link shown in the toast. */
  action?: { label: string; to: string };
}

export interface Toast extends ToastInput {
  id: string;
}

export interface ToastValue {
  toast: (input: ToastInput) => string;
  dismiss: (id: string) => void;
}

export const ToastContext = createContext<ToastValue | null>(null);

/** Access the toast API; must be used inside `ToastProvider`. */
export function useToast(): ToastValue {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToast must be used inside ToastProvider.");
  return value;
}

/**
 * Toast for errors that need attention wherever they happen:
 * 401 (API key), 429 (rate limit) and unreachable server. Other errors return null
 * and are shown next to the feature that failed.
 */
export function toastForError(error: unknown): ToastInput | null {
  if (!(error instanceof ApiError)) return null;
  if (error.status === 401) {
    return {
      id: "global-auth",
      tone: "error",
      title: "API key required or invalid",
      description: "Save a valid API key in Settings to use the studio.",
      action: { label: "Open Settings", to: "/settings" },
    };
  }
  if (error.status === 429) {
    const wait = error.retryAfter ?? 1;
    return {
      id: "global-rate-limit",
      tone: "warning",
      title: `Too many requests. Try again in ${wait} s.`,
    };
  }
  // `backend_unavailable`: the proxy in front of the API (nginx) could not reach it.
  if (error.code === "network_error" || error.code === "backend_unavailable") {
    return { id: "global-network", tone: "error", title: "Cannot reach the server." };
  }
  return null;
}
