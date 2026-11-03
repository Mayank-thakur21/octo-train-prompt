import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { STORAGE_KEYS } from "../lib/storage";
import { apiError, json, mockApi, route } from "../test/fetchMock";
import { catalogRoutes, MODELS_RESPONSE } from "../test/fixtures";
import { setSystemDark } from "../test/matchMedia";
import { renderWithProviders } from "../test/utils";
import SettingsPage from "./SettingsPage";

describe("SettingsPage", () => {
  it("stores the API key and sends it as X-API-Key when testing the connection", async () => {
    const api = mockApi([
      route("GET", "/api/models", ({ headers }) =>
        headers.get("X-API-Key") === "studio-key-0123456789"
          ? json(MODELS_RESPONSE)
          : apiError(401, "unauthorized", "A valid API key is required."),
      ),
      ...catalogRoutes(),
    ]);
    const { user } = renderWithProviders(<SettingsPage />, { route: "/settings" });
    const input = screen.getByLabelText("API key");
    expect(input).toHaveAttribute("type", "password");
    await user.click(screen.getByRole("button", { name: "Show key" }));
    expect(input).toHaveAttribute("type", "text");

    await user.click(screen.getByRole("button", { name: "Test connection" }));
    expect(await screen.findByText("A valid API key is required.")).toBeInTheDocument();

    await user.type(input, "studio-key-0123456789");
    await user.click(screen.getByRole("button", { name: "Save API key" }));
    expect(window.localStorage.getItem(STORAGE_KEYS.apiKey)).toBe('"studio-key-0123456789"');
    expect(await screen.findByText("API key saved")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Test connection" }));
    expect(await screen.findByText(/models are available/)).toHaveTextContent("3 of 6 models are available.");
    expect(api.callsTo("GET", "/api/models").at(-1)?.headers.get("X-API-Key")).toBe("studio-key-0123456789");

    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(window.localStorage.getItem(STORAGE_KEYS.apiKey)).toBeNull();
    expect(input).toHaveValue("");
  });

  it("applies and stores the theme, following the system in System mode", async () => {
    mockApi(catalogRoutes());
    const { user } = renderWithProviders(<SettingsPage />, { route: "/settings" });
    const root = document.documentElement;
    expect(screen.getByRole("radio", { name: "System" })).toBeChecked();
    expect(root).not.toHaveClass("dark");

    await user.click(screen.getByRole("radio", { name: "Dark" }));
    expect(root).toHaveClass("dark");
    expect(window.localStorage.getItem(STORAGE_KEYS.theme)).toBe('"dark"');

    await user.click(screen.getByRole("radio", { name: "Light" }));
    expect(root).not.toHaveClass("dark");

    await user.click(screen.getByRole("radio", { name: "System" }));
    setSystemDark(true);
    await waitFor(() => expect(root).toHaveClass("dark"));
    setSystemDark(false);
    await waitFor(() => expect(root).not.toHaveClass("dark"));
  });

  it("shows server information from /api/meta", async () => {
    mockApi(catalogRoutes());
    renderWithProviders(<SettingsPage />, { route: "/settings" });
    expect(await screen.findByText("2.0.0")).toBeInTheDocument();
    expect(screen.getByText("Anthropic: configured")).toBeInTheDocument();
    expect(screen.getByText("OpenAI: not configured")).toBeInTheDocument();
    expect(screen.getByText("Request body / import size")).toBeInTheDocument();
  });

  it("exports the selected data and imports a document", async () => {
    const createObjectURL = vi.fn(() => "blob:mock");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const api = mockApi([
      ...catalogRoutes(),
      route("GET", "/api/export", () =>
        json({ format: "prompt-studio-export" }, 200, { "Content-Disposition": 'attachment; filename="export.json"' }),
      ),
      route("POST", "/api/import", {
        prompts: { created: 2, updated: 0, skipped: 1, renamed: 0 },
        suites: { created: 1, updated: 0, skipped: 0, renamed: 0 },
        history: { created: 0 },
        warnings: ["History entry 3 references a version that was not imported."],
      }),
    ]);
    const { user } = renderWithProviders(<SettingsPage />, { route: "/settings" });
    await user.click(screen.getByRole("checkbox", { name: "History" }));
    await user.click(screen.getByRole("button", { name: "Export" }));
    await waitFor(() => expect(click).toHaveBeenCalled());
    expect(api.callsTo("GET", "/api/export")[0]?.url.searchParams.get("include")).toBe("prompts,suites,history");
    expect(createObjectURL).toHaveBeenCalled();

    const file = new File([JSON.stringify({ format: "prompt-studio-export", format_version: 1, prompts: [] })], "backup.json", {
      type: "application/json",
    });
    await user.upload(screen.getByLabelText("Import file"), file);
    await user.selectOptions(screen.getByRole("combobox", { name: "When a name already exists" }), "rename");
    await user.click(screen.getByRole("checkbox", { name: "Convert legacy {placeholders}" }));
    await user.click(screen.getByRole("button", { name: "Import" }));
    expect(await screen.findByText("Prompts: 2 created, 0 updated, 1 skipped, 0 renamed")).toBeInTheDocument();
    expect(screen.getByText("History entry 3 references a version that was not imported.")).toBeInTheDocument();
    const call = api.callsTo("POST", "/api/import")[0];
    expect(call?.url.searchParams.get("conflict")).toBe("rename");
    expect(call?.url.searchParams.get("legacy_placeholders")).toBe("true");
    expect(call?.body).toMatchObject({ format: "prompt-studio-export" });
  });

  it("rejects an import file that is not JSON", async () => {
    const api = mockApi(catalogRoutes());
    const { user } = renderWithProviders(<SettingsPage />, { route: "/settings" });
    await user.upload(screen.getByLabelText("Import file"), new File(["not json"], "x.json", { type: "application/json" }));
    await user.click(screen.getByRole("button", { name: "Import" }));
    expect(await screen.findByText("The file is not valid JSON.")).toBeInTheDocument();
    expect(api.callsTo("POST", "/api/import")).toHaveLength(0);
  });
});
