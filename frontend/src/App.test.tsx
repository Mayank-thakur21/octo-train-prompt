import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";
import { apiError, mockApi, route } from "./test/fetchMock";
import { catalogRoutes, META, page } from "./test/fixtures";
import { currentLocation, renderWithProviders } from "./test/utils";

describe("App shell", () => {
  it("redirects / to the Playground, marks the active link and shows the backend status", async () => {
    mockApi([...catalogRoutes(), route("GET", "/api/history", page([]))]);
    const { user } = renderWithProviders(<App />, { route: "/" });
    expect(await screen.findByRole("heading", { level: 1, name: "Playground" })).toBeInTheDocument();
    expect(currentLocation()).toBe("/playground");
    await waitFor(() => expect(document.title).toBe("Playground · Prompt Engineering Studio"));

    const nav = screen.getAllByRole("navigation", { name: "Main" })[0] as HTMLElement;
    expect(within(nav).getByRole("link", { name: "Playground" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "History" })).not.toHaveAttribute("aria-current");
    for (const label of ["Compare", "Library", "Test suites", "Evaluations", "Settings"]) {
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    }
    expect(await screen.findByText("Online")).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");

    // The skip link is the first focusable element.
    await user.tab();
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveFocus();

    // Client-side navigation moves focus to the new page heading.
    await user.click(within(nav).getByRole("link", { name: "History" }));
    const heading = await screen.findByRole("heading", { level: 1, name: "History" });
    await waitFor(() => expect(heading).toHaveFocus());
    await waitFor(() => expect(document.title).toBe("History · Prompt Engineering Studio"));
  });

  it("shows Offline and the demo badge", async () => {
    mockApi([
      ...catalogRoutes().filter((item) => item.path !== "/api/ready" && item.path !== "/api/meta"),
      route("GET", "/api/meta", { ...META, demo_mode: true }),
      route("GET", "/api/ready", () => apiError(503, "not_ready", "Not ready.")),
    ]);
    renderWithProviders(<App />, { route: "/playground" });
    expect(await screen.findByText("Offline")).toBeInTheDocument();
    expect(await screen.findByText("Demo mode")).toBeInTheDocument();
  });

  it("toggles the theme from the top bar", async () => {
    mockApi(catalogRoutes());
    const { user } = renderWithProviders(<App />, { route: "/playground" });
    await user.click(await screen.findByRole("button", { name: "Switch to dark theme" }));
    expect(document.documentElement).toHaveClass("dark");
    await user.click(screen.getByRole("button", { name: "Switch to light theme" }));
    expect(document.documentElement).not.toHaveClass("dark");
  });

  it("shows a 401 toast that links to Settings", async () => {
    mockApi([
      ...catalogRoutes().filter((item) => item.path !== "/api/models"),
      route("GET", "/api/models", () => apiError(401, "unauthorized", "A valid API key is required.")),
    ]);
    const { user } = renderWithProviders(<App />, { route: "/playground", appClient: true });
    const toastTitle = await screen.findByText("API key required or invalid");
    const toast = toastTitle.closest<HTMLElement>('[role="alert"]');
    expect(toast).not.toBeNull();
    // The page that failed to load offers the same way out next to its error message.
    const main = screen.getByRole("main");
    expect(await within(main).findByRole("link", { name: "Open Settings" })).toHaveAttribute("href", "/settings");
    await user.click(within(toast as HTMLElement).getByRole("link", { name: "Open Settings" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
  });

  it("shows the rate-limit toast with the wait time", async () => {
    mockApi([
      ...catalogRoutes().filter((item) => item.path !== "/api/models"),
      route("GET", "/api/models", () => apiError(429, "rate_limited", "Too many requests.", { retry_after: 12 }, { "Retry-After": "12" })),
    ]);
    renderWithProviders(<App />, { route: "/playground", appClient: true });
    expect(await screen.findByText("Too many requests. Try again in 12 s.")).toBeInTheDocument();
  });

  it("opens the navigation drawer from the menu button", async () => {
    mockApi([...catalogRoutes(), route("GET", "/api/suites", page([]))]);
    const { user } = renderWithProviders(<App />, { route: "/playground" });
    await user.click(screen.getByRole("button", { name: "Open navigation menu" }));
    const drawer = await screen.findByRole("dialog", { name: "Navigation" });
    await user.click(within(drawer).getByRole("link", { name: "Test suites" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 1, name: "Test suites" })).toBeInTheDocument();
  });

  it("renders the not-found page for unknown routes", async () => {
    mockApi(catalogRoutes());
    renderWithProviders(<App />, { route: "/nope" });
    expect(await screen.findByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to the Playground" })).toHaveAttribute("href", "/playground");
  });
});
