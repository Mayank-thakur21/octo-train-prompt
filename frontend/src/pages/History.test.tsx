import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { json, mockApi, route } from "../test/fetchMock";
import { catalogRoutes, historyDetail, historySummary, ID, page } from "../test/fixtures";
import { currentLocation, renderWithProviders } from "../test/utils";
import HistoryDetailPage from "./HistoryDetailPage";
import HistoryPage from "./HistoryPage";

describe("HistoryPage", () => {
  it("lists runs and applies the filters as query parameters", async () => {
    const api = mockApi([
      ...catalogRoutes(),
      route("GET", "/api/history", page([historySummary(), historySummary({ id: "7".repeat(32), status: "error", model: "claude-opus-5-5" })], 2)),
    ]);
    const { user } = renderWithProviders(<HistoryPage />, { route: "/history" });
    const table = await screen.findByRole("table", { name: "Run history" });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByText("Error")).toBeInTheDocument();
    expect(within(table).getAllByText("Hello Ada")).toHaveLength(2);

    await user.selectOptions(screen.getByRole("combobox", { name: "Status" }), "error");
    await user.selectOptions(screen.getByRole("combobox", { name: "Provider" }), "anthropic");
    await user.selectOptions(screen.getByRole("combobox", { name: "Source" }), "compare");
    await user.selectOptions(screen.getByRole("combobox", { name: "Model" }), "claude-opus-5-5");
    await user.type(screen.getByRole("searchbox", { name: "Search history" }), "Ada");
    await waitFor(() => {
      const params = api.callsTo("GET", "/api/history").at(-1)?.url.searchParams;
      expect(Object.fromEntries(params ?? [])).toEqual({
        limit: "20",
        offset: "0",
        q: "Ada",
        model: "claude-opus-5-5",
        provider: "anthropic",
        status: "error",
        source: "compare",
      });
    });
  });

  it("keeps filters, search and page in the URL so Back restores the list", async () => {
    const api = mockApi([...catalogRoutes(), route("GET", "/api/history", page([historySummary()], 45))]);
    const first = renderWithProviders(<HistoryPage />, { route: "/history" });
    await screen.findByRole("table", { name: "Run history" });
    await first.user.selectOptions(screen.getByRole("combobox", { name: "Status" }), "error");
    await first.user.type(screen.getByRole("searchbox", { name: "Search history" }), "Summarize");
    await first.user.click(screen.getByRole("button", { name: /next/i }));
    await waitFor(() => expect(currentLocation()).toBe("/history?status=error&q=Summarize&offset=20"));
    first.unmount();

    // Coming back (Back restores this URL) shows the same filtered page.
    renderWithProviders(<HistoryPage />, { route: "/history?status=error&q=Summarize&offset=20" });
    expect(await screen.findByRole("combobox", { name: "Status" })).toHaveValue("error");
    expect(screen.getByRole("searchbox", { name: "Search history" })).toHaveValue("Summarize");
    await waitFor(() => {
      const params = api.callsTo("GET", "/api/history").at(-1)?.url.searchParams;
      expect(Object.fromEntries(params ?? [])).toEqual({ limit: "20", offset: "20", q: "Summarize", status: "error" });
    });
  });

  it("filters by comparison group from the URL and clears history after confirmation", async () => {
    const api = mockApi([
      ...catalogRoutes(),
      route("GET", "/api/history", page([historySummary({ source: "compare", group_id: ID.comparison })])),
      route("DELETE", "/api/history", { deleted: 4 }),
    ]);
    const { user } = renderWithProviders(<HistoryPage />, { route: `/history?group_id=${ID.comparison}` });
    await screen.findByRole("table", { name: "Run history" });
    expect(api.callsTo("GET", "/api/history")[0]?.url.searchParams.get("group_id")).toBe(ID.comparison);
    await user.click(screen.getByRole("button", { name: "Clear history" }));
    const dialog = await screen.findByRole("dialog", { name: "Clear all history?" });
    await user.click(within(dialog).getByRole("button", { name: "Clear history" }));
    expect(await screen.findByText("Deleted 4 history entries")).toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    mockApi([...catalogRoutes(), route("GET", "/api/history", page([]))]);
    renderWithProviders(<HistoryPage />, { route: "/history" });
    expect(await screen.findByText("No runs yet")).toBeInTheDocument();
  });
});

describe("HistoryDetailPage", () => {
  it("shows every field and navigates to re-run in the Playground", async () => {
    mockApi([
      ...catalogRoutes(),
      route("GET", `/api/history/${ID.history}`, historyDetail({ warnings: ["temperature is not supported."], thinking: "pondering" })),
    ]);
    const { user } = renderWithProviders(<HistoryDetailPage />, { route: `/history/${ID.history}`, path: "/history/:historyId" });
    expect(await screen.findByRole("heading", { level: 1, name: "Run with Demo Concise (offline)" })).toBeInTheDocument();
    expect(screen.getByText("Hello {{name}}")).toBeInTheDocument();
    expect(screen.getAllByText("Hello Ada").length).toBeGreaterThan(0);
    expect(screen.getByText("temperature is not supported.")).toBeInTheDocument();
    expect(screen.getByText("pondering")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open in Playground" })).toHaveAttribute("href", `/playground?history=${ID.history}`);
    await user.click(screen.getByRole("link", { name: "Re-run" }));
    expect(currentLocation()).toBe(`/playground?history=${ID.history}&autorun=1`);
  });

  it("deletes the entry", async () => {
    const api = mockApi([
      ...catalogRoutes(),
      route("GET", `/api/history/${ID.history}`, historyDetail()),
      route("DELETE", `/api/history/${ID.history}`, () => new Response(null, { status: 204 })),
    ]);
    const { user } = renderWithProviders(<HistoryDetailPage />, { route: `/history/${ID.history}`, path: "/history/:historyId" });
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete entry" }));
    await waitFor(() => expect(currentLocation()).toBe("/history"));
    expect(api.callsTo("DELETE", `/api/history/${ID.history}`)).toHaveLength(1);
  });

  it("shows not found for unknown entries", async () => {
    mockApi([
      ...catalogRoutes(),
      route("GET", `/api/history/${ID.history}`, () => json({ error: { code: "not_found", message: "History entry not found." } }, 404)),
    ]);
    renderWithProviders(<HistoryDetailPage />, { route: `/history/${ID.history}`, path: "/history/:historyId" });
    expect(await screen.findByRole("heading", { level: 1, name: "History entry not found" })).toBeInTheDocument();
    expect(screen.getByText("History entry not found.")).toBeInTheDocument();
  });
});
