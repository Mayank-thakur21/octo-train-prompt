import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { json, mockApi, route } from "../test/fetchMock";
import { catalogRoutes, ID, page, promptDetail, promptSummary, VERSION_DIFF, versionDetail } from "../test/fixtures";
import { currentLocation, renderWithProviders } from "../test/utils";
import LibraryPage from "./LibraryPage";
import PromptDetailPage from "./PromptDetailPage";

describe("LibraryPage", () => {
  it("searches (debounced), filters by tag and links to the prompt", async () => {
    const api = mockApi([
      ...catalogRoutes(),
      route("GET", "/api/prompts", ({ url }) =>
        json(page(url.searchParams.get("q") === "nothing" ? [] : [promptSummary()])),
      ),
      route("GET", "/api/tags", { tags: [{ tag: "writing", count: 1 }, { tag: "code", count: 3 }] }),
    ]);
    const { user } = renderWithProviders(<LibraryPage />, { route: "/library" });
    const list = await screen.findByRole("list", { name: "Prompts" });
    expect(within(list).getByRole("link", { name: "Summarizer" })).toHaveAttribute("href", `/library/${ID.prompt}`);
    expect(within(list).getByText("2 versions")).toBeInTheDocument();

    await user.type(screen.getByRole("searchbox", { name: "Search prompts" }), "sum");
    await waitFor(() =>
      expect(api.callsTo("GET", "/api/prompts").some((call) => call.url.searchParams.get("q") === "sum")).toBe(true),
    );
    // Debounced: no request for the partial input "s" or "su".
    expect(api.callsTo("GET", "/api/prompts").some((call) => call.url.searchParams.get("q") === "s")).toBe(false);

    await user.click(screen.getByRole("button", { name: "code (3)" }));
    expect(screen.getByRole("button", { name: "code (3)" })).toHaveAttribute("aria-pressed", "true");
    await waitFor(() =>
      expect(api.callsTo("GET", "/api/prompts").some((call) => call.url.searchParams.getAll("tag").includes("code"))).toBe(true),
    );

    await user.selectOptions(screen.getByRole("combobox", { name: "Show" }), "all");
    await waitFor(() =>
      expect(api.callsTo("GET", "/api/prompts").some((call) => call.url.searchParams.get("archived") === "all")).toBe(true),
    );

    await user.clear(screen.getByRole("searchbox", { name: "Search prompts" }));
    await user.type(screen.getByRole("searchbox", { name: "Search prompts" }), "nothing");
    expect(await screen.findByText("No prompts match these filters")).toBeInTheDocument();
  });

  it("shows an empty state that links to the Playground", async () => {
    mockApi([...catalogRoutes(), route("GET", "/api/prompts", page([])), route("GET", "/api/tags", { tags: [] })]);
    renderWithProviders(<LibraryPage />, { route: "/library" });
    expect(await screen.findByText("Your library is empty")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the Playground" })).toHaveAttribute("href", "/playground");
  });

  it("creates a prompt from the New prompt dialog", async () => {
    const api = mockApi([
      ...catalogRoutes(),
      route("GET", "/api/prompts", page([])),
      route("GET", "/api/tags", { tags: [] }),
      route("POST", "/api/prompts", () => json(promptDetail(), 201)),
    ]);
    const { user } = renderWithProviders(<LibraryPage />, { route: "/library" });
    await user.click(await screen.findByRole("button", { name: "New prompt" }));
    const dialog = await screen.findByRole("dialog", { name: "New prompt" });
    await user.type(within(dialog).getByLabelText("Name"), "Summarizer");
    await user.click(within(dialog).getByLabelText("User prompt"));
    await user.paste("Summarize {{text}}");
    await user.click(within(dialog).getByRole("button", { name: "Save prompt" }));
    await waitFor(() => expect(currentLocation()).toBe(`/library/${ID.prompt}`));
    expect(api.callsTo("POST", "/api/prompts")[0]?.body).toMatchObject({ name: "Summarizer", prompt: "Summarize {{text}}", system: null });
  });
});

describe("PromptDetailPage", () => {
  function detailRoutes() {
    return [
      ...catalogRoutes(),
      route("GET", `/api/prompts/${ID.prompt}`, promptDetail()),
      route("GET", `/api/prompts/${ID.prompt}/versions`, page([
        { id: ID.version2, prompt_id: ID.prompt, version: 2, notes: "Added count", created_at: versionDetail(2).created_at, variables: ["text", "count"] },
        { id: ID.version1, prompt_id: ID.prompt, version: 1, notes: "", created_at: versionDetail(1).created_at, variables: ["text"] },
      ])),
      route("GET", `/api/prompts/${ID.prompt}/versions/1`, versionDetail(1)),
      route("GET", `/api/prompts/${ID.prompt}/diff`, VERSION_DIFF),
    ];
  }

  it("renders the side-by-side and unified diff of the selected versions", async () => {
    const api = mockApi(detailRoutes());
    const { user } = renderWithProviders(<PromptDetailPage />, { route: `/library/${ID.prompt}`, path: "/library/:promptId" });
    expect(await screen.findByRole("heading", { level: 1, name: "Summarizer" })).toBeInTheDocument();
    const diff = await screen.findByRole("region", { name: "User prompt diff" });
    expect(within(diff).getByText(/removed:/)).toBeInTheDocument();
    expect(within(diff).getByText(/added:/)).toBeInTheDocument();
    const diffCall = api.callsTo("GET", `/api/prompts/${ID.prompt}/diff`)[0];
    expect(diffCall?.url.searchParams.get("from_version")).toBe("1");
    expect(diffCall?.url.searchParams.get("to_version")).toBe("2");
    expect(screen.getByText("Settings unchanged")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Unified" }));
    expect(screen.getByRole("tabpanel")).toHaveTextContent("+Summarize {{text}} in {{count|3}} bullets");
  });

  it("restores an older version", async () => {
    const api = mockApi([
      ...detailRoutes(),
      route("POST", `/api/prompts/${ID.prompt}/versions/1/restore`, () =>
        json(versionDetail(3, { id: "4".repeat(32), notes: "Restored from v1", prompt: "Summarize {{text}}" }), 201),
      ),
      route("GET", `/api/prompts/${ID.prompt}/versions/3`, versionDetail(3, { id: "4".repeat(32) })),
    ]);
    const { user } = renderWithProviders(<PromptDetailPage />, { route: `/library/${ID.prompt}`, path: "/library/:promptId" });
    await user.click(await screen.findByRole("button", { name: /^v1/ }));
    expect(await screen.findByRole("heading", { name: "Version 1" })).toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: "Open in Playground" }).map((link) => link.getAttribute("href")),
    ).toContain(`/playground?prompt=${ID.prompt}&version=1`);
    await user.click(screen.getByRole("button", { name: "Restore" }));
    expect(await screen.findByText("Restored v1 as v3")).toBeInTheDocument();
    expect(api.callsTo("POST", `/api/prompts/${ID.prompt}/versions/1/restore`)).toHaveLength(1);
  });

  it("archives and deletes with confirmation", async () => {
    const api = mockApi([
      ...detailRoutes(),
      route("PATCH", `/api/prompts/${ID.prompt}`, () => json(promptDetail({ archived: true }))),
      route("DELETE", `/api/prompts/${ID.prompt}`, () => new Response(null, { status: 204 })),
    ]);
    const { user } = renderWithProviders(<PromptDetailPage />, { route: `/library/${ID.prompt}`, path: "/library/:promptId" });
    await user.click(await screen.findByRole("button", { name: "Archive" }));
    expect(await screen.findByText("Prompt archived")).toBeInTheDocument();
    expect(api.callsTo("PATCH", `/api/prompts/${ID.prompt}`)[0]?.body).toEqual({ archived: true });

    await user.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete this prompt?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete prompt" }));
    await waitFor(() => expect(currentLocation()).toBe("/library"));
  });
});
