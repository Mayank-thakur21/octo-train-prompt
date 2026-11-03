import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CompareCell, CompareResult } from "../api/types";
import { readStorage, STORAGE_KEYS } from "../lib/storage";
import { apiError, controlledSse, mockApi, route, sseFrame } from "../test/fetchMock";
import { catalogRoutes, ID, NOW, runResult } from "../test/fixtures";
import { currentLocation, renderWithProviders } from "../test/utils";
import ComparePage from "./ComparePage";

const MODELS = ["claude-opus-5-5", "demo-concise"];

function cell(index: number, overrides: Partial<CompareCell> = {}): CompareCell {
  const variantIndex = Math.floor(index / 2);
  const model = MODELS[index % 2] ?? "demo-concise";
  return {
    index,
    variant_index: variantIndex,
    model,
    provider: model === "demo-concise" ? "demo" : "anthropic",
    variant_label: variantIndex === 0 ? "Formal" : "Variant B",
    status: "ok",
    result: runResult({ model, text: `Answer ${index}`, latency_ms: 100 + index * 100 }),
    error: null,
    ...overrides,
  };
}

describe("ComparePage", () => {
  it("runs variants x models and fills the grid from cell events", async () => {
    const stream = controlledSse();
    const api = mockApi([...catalogRoutes(), route("POST", "/api/compare/stream", () => stream.response)]);
    const { user } = renderWithProviders(<ComparePage />, { route: "/compare" });

    const firstPrompt = (await screen.findAllByLabelText("User prompt"))[0] as HTMLElement;
    await user.click(firstPrompt);
    await user.paste("Greet {{name}} formally");
    await user.type(screen.getAllByLabelText("Label")[0] as HTMLElement, "Formal");
    await user.click(screen.getByRole("button", { name: "Add variant" }));
    const secondPrompt = screen.getAllByLabelText("User prompt")[1] as HTMLElement;
    await user.click(secondPrompt);
    await user.paste("Greet {{name}} casually");
    await user.type(await screen.findByLabelText("name"), "Ada");

    expect(screen.getByRole("checkbox", { name: "Claude Opus 5.5" })).toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "Demo Concise (offline)" }));
    expect(screen.getByText("2 x 2 = 4 / 12 cells")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Run comparison" }));
    await waitFor(() => expect(api.callsTo("POST", "/api/compare/stream")).toHaveLength(1));
    expect(api.callsTo("POST", "/api/compare/stream")[0]?.body).toEqual({
      variants: [
        { label: "Formal", system: null, prompt: "Greet {{name}} formally" },
        { label: null, system: null, prompt: "Greet {{name}} casually" },
      ],
      models: MODELS,
      variables: { name: "Ada" },
      temperature: null,
      max_tokens: null,
      thinking: false,
    });

    stream.push(
      sseFrame("start", {
        comparison_id: ID.comparison,
        created_at: NOW,
        cells: [0, 1, 2, 3].map((index) => ({
          index,
          variant_index: Math.floor(index / 2),
          model: MODELS[index % 2],
          provider: "demo",
        })),
        warnings: [],
      }),
    );
    const grid = screen.getByRole("region", { name: "Comparison results" });
    expect(screen.getByText("Comparison running: 4 cells.")).toHaveAttribute("role", "status");
    expect(within(grid).getByRole("columnheader", { name: "Claude Opus 5.5" })).toBeInTheDocument();
    expect(within(grid).getByRole("rowheader", { name: "Variant B" })).toBeInTheDocument();
    expect(within(grid).getAllByRole("status")).toHaveLength(4);

    stream.push(sseFrame("cell", cell(1)));
    expect(await within(grid).findByText("Answer 1")).toBeInTheDocument();
    expect(within(grid).getAllByRole("status")).toHaveLength(3);
    stream.push(
      sseFrame("cell", cell(2, { status: "error", result: null, error: { code: "provider_timeout", message: "The Demo API did not respond in time." } })),
    );
    expect(await within(grid).findByText("The Demo API did not respond in time.")).toBeInTheDocument();

    const result: CompareResult = {
      id: ID.comparison,
      created_at: NOW,
      variants: [],
      models: MODELS,
      variables: { name: "Ada" },
      params: { temperature: null, max_tokens: 4096, thinking: false },
      cells: [cell(0), cell(1), cell(2, { status: "error", result: null, error: { code: "provider_timeout", message: "The Demo API did not respond in time." } }), cell(3)],
      summary: { ok_count: 3, error_count: 1, fastest_cell: 0, cheapest_cell: null },
      warnings: [],
    };
    stream.push(sseFrame("done", result));
    stream.close();
    expect(await within(grid).findByText("Answer 3")).toBeInTheDocument();
    expect(within(grid).getByText("Fastest")).toBeInTheDocument();
    expect(screen.getByText(/^3 succeeded, 1 failed\./)).toBeInTheDocument();
    expect(screen.getByText("Comparison finished: 3 succeeded, 1 failed.")).toHaveAttribute("role", "status");
    await user.click(screen.getByRole("link", { name: "View in history" }));
    expect(currentLocation()).toBe(`/history?group_id=${ID.comparison}`);
  });

  it("disables Run above the cell cap and Stop aborts", async () => {
    const stream = controlledSse();
    mockApi([...catalogRoutes(), route("POST", "/api/compare/stream", () => stream.response)]);
    const { user } = renderWithProviders(<ComparePage />, { route: "/compare" });
    const prompt = (await screen.findAllByLabelText("User prompt"))[0] as HTMLElement;
    expect(screen.getByRole("button", { name: "Run comparison" })).toBeDisabled();
    await user.click(prompt);
    await user.paste("Hi");
    await user.click(screen.getByRole("button", { name: "Run comparison" }));
    await user.click(await screen.findByRole("button", { name: "Stop" }));
    expect(await screen.findByText("Stopped before this cell finished.")).toBeInTheDocument();
    expect(stream.cancelled()).toBe(true);
  });

  it("marks a variable required when one variant has no default, and hides the grid when the run is rejected", async () => {
    const api = mockApi([
      ...catalogRoutes(),
      route("POST", "/api/compare/stream", () =>
        apiError(422, "missing_variables", "Some template variables have no value: text.", { missing: ["text"] }),
      ),
    ]);
    const { user } = renderWithProviders(<ComparePage />, { route: "/compare" });
    await user.click((await screen.findAllByLabelText("User prompt"))[0] as HTMLElement);
    await user.paste("Summarize {{text|the release notes}} for a manager.");
    await user.click(screen.getByRole("button", { name: "Add variant" }));
    await user.click(screen.getAllByLabelText("User prompt")[1] as HTMLElement);
    await user.paste("Summarize {{text}} in one sentence.");

    const field = await screen.findByLabelText("text");
    await waitFor(() => expect(field).toBeRequired());
    expect(field).not.toHaveAttribute("placeholder", "the release notes");

    await user.click(screen.getByRole("button", { name: "Run comparison" }));
    await waitFor(() => expect(api.callsTo("POST", "/api/compare/stream")).toHaveLength(1));
    expect(await screen.findByText("The comparison could not run")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Comparison results" })).not.toBeInTheDocument();
  });

  it("keeps the variable optional when every variant has a default", async () => {
    mockApi(catalogRoutes());
    const { user } = renderWithProviders(<ComparePage />, { route: "/compare" });
    await user.click((await screen.findAllByLabelText("User prompt"))[0] as HTMLElement);
    await user.paste("Say {{word|hi}}");
    await user.click(screen.getByRole("button", { name: "Add variant" }));
    await user.click(screen.getAllByLabelText("User prompt")[1] as HTMLElement);
    await user.paste("SAY {{word|hello}}");
    const field = await screen.findByLabelText("word");
    await waitFor(() => expect(field).toHaveAttribute("placeholder", "hi"));
    expect(field).not.toBeRequired();
  });

  it("saves the draft at once when leaving the page", async () => {
    mockApi(catalogRoutes());
    const { user, unmount } = renderWithProviders(<ComparePage />, { route: "/compare" });
    await user.click((await screen.findAllByLabelText("User prompt"))[0] as HTMLElement);
    await user.paste("Typed just before leaving");
    unmount();
    const draft = readStorage<{ variants?: Array<{ prompt: string }> }>(STORAGE_KEYS.compareDraft, {});
    expect(draft.variants?.[0]?.prompt).toBe("Typed just before leaving");
  });
});
