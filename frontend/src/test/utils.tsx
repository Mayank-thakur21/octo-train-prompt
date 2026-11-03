/** Rendering helpers that wrap components in the same providers as the app. */
import { QueryClient } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { QueryProvider } from "../context/QueryProvider";
import { SettingsProvider } from "../context/SettingsProvider";
import { ToastProvider } from "../context/ToastProvider";

/** Shows the current location so tests can assert navigation. */
function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="location" hidden>
      {`${location.pathname}${location.search}`}
    </output>
  );
}

export interface RenderOptions {
  /** Initial URL, e.g. "/library/abc". */
  route?: string;
  /** Route pattern for the element, e.g. "/library/:promptId" (defaults to "*"). */
  path?: string;
  /** Use the app's real QueryClient (global error toasts) instead of a quiet test client. */
  appClient?: boolean;
}

export interface RenderWithProvidersResult extends RenderResult {
  user: UserEvent;
  /** The quiet test client (null when `appClient` is used). */
  queryClient: QueryClient | null;
}

/** Quiet test QueryClient: no retries and no global error toasts. */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } } });
}

/** Renders `ui` inside MemoryRouter, SettingsProvider, ToastProvider and QueryProvider. */
export function renderWithProviders(ui: ReactElement, options: RenderOptions = {}): RenderWithProvidersResult {
  const { route = "/", path = "*", appClient = false } = options;
  const user = userEvent.setup();
  const client = appClient ? null : createTestQueryClient();
  const tree = (
    <MemoryRouter initialEntries={[route]}>
      <SettingsProvider>
        <ToastProvider>
          <QueryProvider client={client ?? undefined}>
            <Routes>
              <Route path={path} element={ui} />
              {path !== "*" ? <Route path="*" element={null} /> : null}
            </Routes>
            <LocationProbe />
          </QueryProvider>
        </ToastProvider>
      </SettingsProvider>
    </MemoryRouter>
  );
  const result = render(tree);
  return { ...result, user, queryClient: client };
}

/** Current location rendered by the probe. */
export function currentLocation(container: HTMLElement = document.body): string {
  return container.querySelector('[data-testid="location"]')?.textContent ?? "";
}
