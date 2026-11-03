import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { readStorage, STORAGE_KEYS, writeStorage } from "../lib/storage";
import { apiError, controlledSse, json, mockApi, route, sseFrame } from "../test/fetchMock";
import { catalogRoutes, historyDetail, ID, NOW, promptDetail, runResult, versionDetail } from "../test/fixtures";
import { currentLocation, renderWithProviders } from "../test/utils";
import PlaygroundPage from "./PlaygroundPage";

const START = { run_id: ID.run, model: "claude-opus-5-5", provider: "anthropic", created_at: NOW, warnings: [] };

async function typePrompt(user: ReturnType<typeof renderWithProviders>["user"], text: string) {
  const prompt = await screen.findByLabelText("User prompt");
  await user.click(prompt);
  await user.paste(text);
}

describe("PlaygroundPage", () => {
  it("streams a run: variables are sent, deltas appear live and metrics show after done", async () => {
    const stream = controlledSse();
    const api = mockApi([...catalogRoutes(), route("POST", "/api/runs/stream", () => stream.response)]);
    const { user } = renderWithProviders(<PlaygroundPage />, { route: "/playground" });

    await typePrompt(user, "Hello {{name}} in a {{tone|friendly}} tone");
    const nameField = await screen.findByLabelText("name");
    expect(screen.getByLabelText("tone")).toHaveAttribute("placeholder", "friendly");
    await user.type(nameField, "Ada");
    await user.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => expect(api.callsTo("POST", "/api/runs/stream")).toHaveLength(1));
    const body = api.callsTo("POST", "/api/runs/stream")[0]?.body;
    expect(body).toEqual({
      model: "claude-opus-5-5",
      system: null,
      prompt: "Hello {{name}} in a {{tone|friendly}} tone",
      variables: { name: "Ada" },
      temperature: null,
      max_tokens: 4096,
      thinking: false,
      prompt_version_id: null,
    });

    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    const announcer = within(screen.getByRole("region", { name: "Model output" })).getByRole("status");
    expect(announcer).toHaveTextContent("Streaming the answer…");
    stream.push(sseFrame("start", START));
    stream.push(sseFrame("delta", { type: "thinking", text: "Planning a greeting" }));
    stream.push(sseFrame("delta", { type: "text", text: "Hel" }) + "event: delta\ndata: {\"type\":\"text\",");
    stream.push('"text":"lo **Ada**"}\n\n');
    const output = screen.getByRole("region", { name: "Model output" });
    await within(output).findByText("Ada");
    expect(output).toHaveTextContent("Hello Ada");
    expect(within(output).getByText("Thinking")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Run metrics" })).not.toBeInTheDocument();

    stream.push(sseFrame("done", runResult({ text: "Hello **Ada**", thinking: "Planning a greeting" })));
    stream.close();
    const metrics = await screen.findByRole("region", { name: "Run metrics" });
    expect(announcer).toHaveTextContent(/^Run finished: \d+ output tokens\.$/);
    expect(metrics).toHaveTextContent("Claude Opus 5.5");
    expect(metrics).toHaveTextContent("1.2 s");
    expect(metrics).toHaveTextContent("210 ms");
    expect(metrics).toHaveTextContent("$0.0042");
    expect(metrics).toHaveTextContent("Completed");
    expect(screen.getByRole("button", { name: "Run" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "history" })).toHaveAttribute("href", `/history/${ID.run}`);
  });

  it("Stop aborts the stream and keeps the partial output", async () => {
    const stream = controlledSse();
    mockApi([...catalogRoutes(), route("POST", "/api/runs/stream", () => stream.response)]);
    const { user } = renderWithProviders(<PlaygroundPage />, { route: "/playground" });
    await typePrompt(user, "Tell a long story");
    await user.click(screen.getByRole("button", { name: "Run" }));
    stream.push(sseFrame("start", START) + sseFrame("delta", { type: "text", text: "Once upon a time" }));
    const output = screen.getByRole("region", { name: "Model output" });
    await within(output).findByText("Once upon a time");

    await user.click(screen.getByRole("button", { name: "Stop" }));
    expect(await within(output).findByText("Stopped")).toBeInTheDocument();
    expect(within(output).getByRole("status")).toHaveTextContent("Run stopped.");
    expect(output).toHaveTextContent("Once upon a time");
    expect(stream.cancelled()).toBe(true);
    expect(screen.getByRole("button", { name: "Run" })).toBeInTheDocument();
  });

  it("Ctrl+Enter runs from anywhere on the page and stream errors are shown", async () => {
    const api = mockApi([
      ...catalogRoutes(),
      route("POST", "/api/runs/stream", () =>
        apiError(422, "missing_variables", "Missing template variables.", { missing: ["topic"] }),
      ),
    ]);
    const { user } = renderWithProviders(<PlaygroundPage />, { route: "/playground" });
    await typePrompt(user, "Write about {{topic}}");
    await screen.findByLabelText("topic");
    await user.keyboard("{Control>}{Enter}{/Control}");
    await waitFor(() => expect(api.callsTo("POST", "/api/runs/stream")).toHaveLength(1));
    const output = screen.getByRole("region", { name: "Model output" });
    expect(await within(output).findByText("Missing template variables.")).toBeInTheDocument();
    expect(within(output).getByText("Missing variables: topic")).toBeInTheDocument();
    expect(screen.getByLabelText("topic")).toHaveAccessibleDescription("A value is required.");
  });

  it("shows the token estimate method", async () => {
    mockApi(catalogRoutes());
    const { user } = renderWithProviders(<PlaygroundPage />, { route: "/playground" });
    await typePrompt(user, "Count my tokens");
    expect(await screen.findByText("42 tokens", {}, { timeout: 2000 })).toHaveAccessibleDescription(
      "Exact count from the Anthropic token counting API.",
    );
  });

  it("saves as a prompt, then a new version reports no changes", async () => {
    const created = promptDetail({ name: "Greeter", version_count: 1, latest_version: versionDetail(1, { prompt: "Hi there" }) });
    const api = mockApi([
      ...catalogRoutes(),
      route("POST", "/api/prompts", () => json(created, 201)),
      route("POST", `/api/prompts/${ID.prompt}/versions`, () =>
        apiError(409, "no_changes", "The new version is identical to the latest version."),
      ),
    ]);
    const { user } = renderWithProviders(<PlaygroundPage />, { route: "/playground" });
    await typePrompt(user, "Hi there");
    await user.click(screen.getByRole("button", { name: "Save as prompt" }));
    const dialog = await screen.findByRole("dialog", { name: "Save as prompt" });
    await user.type(within(dialog).getByLabelText("Name"), "Greeter");
    await user.type(within(dialog).getByLabelText("Tags"), "greeting, demo");
    await user.click(within(dialog).getByRole("button", { name: "Save prompt" }));

    await screen.findByText('Saved "Greeter" to the library');
    expect(screen.getByRole("link", { name: "Open in Library" })).toHaveAttribute("href", `/library/${ID.prompt}`);
    expect(api.callsTo("POST", "/api/prompts")[0]?.body).toEqual({
      name: "Greeter",
      description: "",
      tags: ["greeting", "demo"],
      system: null,
      prompt: "Hi there",
      notes: "",
      settings: { model: "claude-opus-5-5", temperature: null, max_tokens: 4096, thinking: false },
    });

    await user.click(screen.getByRole("button", { name: "Save new version" }));
    const versionDialog = await screen.findByRole("dialog", { name: "Save new version" });
    await user.click(within(versionDialog).getByRole("button", { name: "Save version" }));
    expect(await screen.findByText("No changes since the latest version.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("Run with an out-of-range max tokens value focuses the field instead of silently changing it", async () => {
    const api = mockApi(catalogRoutes());
    const { user } = renderWithProviders(<PlaygroundPage />, { route: "/playground" });
    await typePrompt(user, "Hi");
    const maxTokens = screen.getByRole("spinbutton", { name: "Max tokens" });
    await user.clear(maxTokens);
    await user.type(maxTokens, "99999");
    await user.click(screen.getByRole("button", { name: "Run" }));
    expect(maxTokens).toHaveValue(99999);
    expect(maxTokens).toHaveFocus();
    expect(maxTokens).toHaveAttribute("aria-invalid", "true");
    expect(api.callsTo("POST", "/api/runs/stream")).toHaveLength(0);
  });

  it("restores the saved draft", async () => {
    writeStorage(STORAGE_KEYS.playgroundDraft, {
      system: "Be nice.",
      prompt: "Draft prompt",
      values: {},
      model: "demo-concise",
      params: { temperature: 0.4, maxTokens: 300, thinking: true },
      linked: null,
    });
    mockApi(catalogRoutes());
    renderWithProviders(<PlaygroundPage />, { route: "/playground" });
    expect(await screen.findByLabelText("User prompt")).toHaveValue("Draft prompt");
    expect(screen.getByLabelText("System prompt")).toHaveValue("Be nice.");
    expect(screen.getByRole("combobox", { name: "Model" })).toHaveValue("demo-concise");
    expect(screen.getByRole("spinbutton", { name: "Max tokens" })).toHaveValue(300);
    expect(screen.getByRole("switch", { name: "Show thinking" })).toBeChecked();
  });

  it("loads a library version and links the run to it", async () => {
    const stream = controlledSse();
    const api = mockApi([
      ...catalogRoutes(),
      route("GET", `/api/prompts/${ID.prompt}`, promptDetail()),
      route("GET", `/api/prompts/${ID.prompt}/versions/1`, versionDetail(1)),
      route("POST", "/api/runs/stream", () => stream.response),
    ]);
    const { user } = renderWithProviders(<PlaygroundPage />, { route: `/playground?prompt=${ID.prompt}&version=1` });
    expect(await screen.findByLabelText("User prompt")).toHaveValue("Summarize {{text}}");
    expect(screen.getByRole("link", { name: "Summarizer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save new version" })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "Max tokens" })).toHaveValue(1024);
    await user.type(await screen.findByLabelText("text"), "Some text");
    await user.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(api.callsTo("POST", "/api/runs/stream")).toHaveLength(1));
    expect(api.callsTo("POST", "/api/runs/stream")[0]?.body).toMatchObject({
      prompt_version_id: ID.version1,
      variables: { text: "Some text" },
      max_tokens: 1024,
    });
    stream.close();
  });

  it("keeps edits to a library prompt after a reload: the ?prompt= link is used once", async () => {
    mockApi([
      ...catalogRoutes(),
      route("GET", `/api/prompts/${ID.prompt}`, promptDetail()),
      route("GET", `/api/prompts/${ID.prompt}/versions/1`, versionDetail(1)),
    ]);
    const first = renderWithProviders(<PlaygroundPage />, { route: `/playground?prompt=${ID.prompt}&version=1` });
    const editor = await screen.findByLabelText("User prompt");
    expect(editor).toHaveValue("Summarize {{text}}");
    await waitFor(() => expect(currentLocation()).toBe("/playground"));
    await first.user.click(editor);
    await first.user.paste(" NEW INSTRUCTION");
    // Leaving the page right away (before the save delay) still saves the edit.
    first.unmount();
    expect(readStorage<{ prompt?: string }>(STORAGE_KEYS.playgroundDraft, {}).prompt).toBe("Summarize {{text}} NEW INSTRUCTION");

    renderWithProviders(<PlaygroundPage />, { route: "/playground" });
    expect(await screen.findByLabelText("User prompt")).toHaveValue("Summarize {{text}} NEW INSTRUCTION");
    // Still linked to the library version, now marked as edited.
    expect(screen.getByRole("link", { name: "Summarizer" })).toBeInTheDocument();
    expect(screen.getByText("edited")).toBeInTheDocument();
  });

  it.each([
    ["template", "?template=summarizer", "Summarize the following text in 3 bullet points:\n\n{{text}}"],
    ["history", `?history=${ID.history}`, "Hello {{name}}"],
  ])("loads a %s link once and then keeps the draft", async (_kind, query, loadedPrompt) => {
    mockApi([...catalogRoutes(), route("GET", `/api/history/${ID.history}`, historyDetail())]);
    const first = renderWithProviders(<PlaygroundPage />, { route: `/playground${query}` });
    const editor = await screen.findByLabelText("User prompt");
    expect(editor).toHaveValue(loadedPrompt);
    await waitFor(() => expect(currentLocation()).toBe("/playground"));
    await first.user.click(editor);
    await first.user.paste(" EDIT TWO");
    first.unmount();
    renderWithProviders(<PlaygroundPage />, { route: "/playground" });
    expect(await screen.findByLabelText("User prompt")).toHaveValue(`${loadedPrompt} EDIT TWO`);
  });

  it("saves a pending draft when the page is hidden", async () => {
    mockApi(catalogRoutes());
    const { user } = renderWithProviders(<PlaygroundPage />, { route: "/playground" });
    await typePrompt(user, "First line");
    window.dispatchEvent(new Event("pagehide"));
    expect(readStorage<{ prompt?: string }>(STORAGE_KEYS.playgroundDraft, {}).prompt).toBe("First line");
  });

  it("re-runs a history entry automatically with autorun=1", async () => {
    const stream = controlledSse();
    const api = mockApi([
      ...catalogRoutes(),
      route("GET", `/api/history/${ID.history}`, historyDetail()),
      route("POST", "/api/runs/stream", () => stream.response),
    ]);
    renderWithProviders(<PlaygroundPage />, { route: `/playground?history=${ID.history}&autorun=1` });
    await waitFor(() => expect(api.callsTo("POST", "/api/runs/stream")).toHaveLength(1));
    expect(api.callsTo("POST", "/api/runs/stream")[0]?.body).toEqual({
      model: "demo-concise",
      system: "Be brief.",
      prompt: "Hello {{name}}",
      variables: { name: "Ada" },
      temperature: 0.7,
      max_tokens: 512,
      thinking: false,
      prompt_version_id: null,
    });
    stream.push(sseFrame("start", { ...START, model: "demo-concise", provider: "demo" }));
    stream.push(sseFrame("done", runResult({ model: "demo-concise", provider: "demo", text: "Hi Ada" })));
    stream.close();
    expect(await screen.findByRole("region", { name: "Run metrics" })).toHaveTextContent("Demo Concise (offline)");
  });

  it("fills the editor from a template", async () => {
    mockApi(catalogRoutes());
    const { user } = renderWithProviders(<PlaygroundPage />, { route: "/playground" });
    await user.click(await screen.findByRole("button", { name: "Templates" }));
    const dialog = await screen.findByRole("dialog", { name: "Templates" });
    await user.click(await within(dialog).findByRole("button", { name: /Summarizer/ }));
    expect(screen.getByLabelText("System prompt")).toHaveValue("You are a concise summarizer.");
    expect(screen.getByLabelText("User prompt")).toHaveValue("Summarize the following text in 3 bullet points:\n\n{{text}}");
  });
});
