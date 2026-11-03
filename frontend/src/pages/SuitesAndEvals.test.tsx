import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { EvalRunDetail } from "../api/types";
import { apiError, json, mockApi, route } from "../test/fetchMock";
import { catalogRoutes, evalDetail, ID, NOW, page, promptSummary, suiteDetail } from "../test/fixtures";
import { currentLocation, renderWithProviders } from "../test/utils";
import EvalDetailPage, { EVAL_POLL_INTERVAL_MS } from "./EvalDetailPage";
import EvalsPage from "./EvalsPage";
import SuiteDetailPage from "./SuiteDetailPage";
import SuitesPage from "./SuitesPage";

describe("SuitesPage", () => {
  it("lists suites and creates a new one", async () => {
    const api = mockApi([
      ...catalogRoutes(),
      route("GET", "/api/suites", page([{ ...suiteDetail(), cases: undefined }])),
      route("POST", "/api/suites", () => json(suiteDetail(), 201)),
    ]);
    const { user } = renderWithProviders(<SuitesPage />, { route: "/suites" });
    expect(await screen.findByRole("link", { name: "Greeting suite" })).toHaveAttribute("href", `/suites/${ID.suite}`);
    expect(screen.getByText("Never evaluated")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "New suite" }));
    const dialog = await screen.findByRole("dialog", { name: "New test suite" });
    await user.click(within(dialog).getByRole("button", { name: "Create suite" }));
    expect(within(dialog).getByText("Enter a name.")).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText("Name"), "Greeting suite");
    await user.click(within(dialog).getByRole("button", { name: "Create suite" }));
    await waitFor(() => expect(currentLocation()).toBe(`/suites/${ID.suite}`));
    expect(api.callsTo("POST", "/api/suites")[0]?.body).toEqual({ name: "Greeting suite", description: "" });
  });
});

describe("SuiteDetailPage", () => {
  function suiteRoutes() {
    return [
      ...catalogRoutes(),
      route("GET", `/api/suites/${ID.suite}`, suiteDetail()),
      route("GET", "/api/prompts", page([promptSummary()])),
      route("GET", `/api/prompts/${ID.prompt}/versions`, page([{ ...promptSummary().latest_version }])),
    ];
  }

  it("adds a case with variables and assertions; server 422 errors show in the form", async () => {
    let attempts = 0;
    const api = mockApi([
      ...suiteRoutes(),
      route("POST", `/api/suites/${ID.suite}/cases`, () => {
        attempts += 1;
        return attempts === 1
          ? apiError(422, "invalid_assertion", "An assertion is invalid.", { assertion_index: 1, reason: "unbalanced parenthesis" })
          : json(suiteDetail().cases[0], 201);
      }),
    ]);
    const { user } = renderWithProviders(<SuiteDetailPage />, { route: `/suites/${ID.suite}`, path: "/suites/:suiteId" });
    expect(await screen.findByRole("heading", { level: 1, name: "Greeting suite" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Says hello" })).toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: "Add case" })[0] as HTMLElement);
    const dialog = await screen.findByRole("dialog", { name: "Add test case" });
    await user.type(within(dialog).getByLabelText("Case name"), "Polite");
    await user.type(within(dialog).getByLabelText("Variable 1 name"), "1bad");
    await user.click(within(dialog).getByRole("button", { name: "Add case" }));
    expect(within(dialog).getByText(/Use letters, digits and _/)).toBeInTheDocument();
    expect(within(dialog).getByText("Enter the expected text.")).toBeInTheDocument();

    await user.clear(within(dialog).getByLabelText("Variable 1 name"));
    await user.type(within(dialog).getByLabelText("Variable 1 name"), "name");
    await user.type(within(dialog).getByLabelText("Variable 1 value"), "Ada");
    await user.type(within(dialog).getByLabelText("Expected text"), "hello");
    await user.click(within(dialog).getByRole("button", { name: "Add assertion" }));
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Assertion 2 type" }), "regex");
    await user.click(within(dialog).getByLabelText("Pattern"));
    await user.paste("(Ada");
    await user.click(within(dialog).getByRole("button", { name: "Add case" }));

    expect(await within(dialog).findByText("assertion 2: unbalanced parenthesis")).toBeInTheDocument();
    expect(within(dialog).getAllByText("unbalanced parenthesis").length).toBeGreaterThan(0);
    expect(api.callsTo("POST", `/api/suites/${ID.suite}/cases`)[0]?.body).toEqual({
      name: "Polite",
      variables: { name: "Ada" },
      assertions: [
        { type: "contains", value: "hello", case_sensitive: false },
        { type: "regex", pattern: "(Ada", flags: "" },
      ],
    });

    await user.clear(within(dialog).getByLabelText("Pattern"));
    await user.type(within(dialog).getByLabelText("Pattern"), "Ada");
    await user.click(within(dialog).getByRole("button", { name: "Add case" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText('Added "Says hello"')).toBeInTheDocument();
  });

  it("a tap outside the case editor closes it only while nothing was typed", async () => {
    mockApi(suiteRoutes());
    const { user } = renderWithProviders(<SuiteDetailPage />, { route: `/suites/${ID.suite}`, path: "/suites/:suiteId" });
    await screen.findByRole("heading", { level: 1, name: "Greeting suite" });
    await user.click(screen.getAllByRole("button", { name: "Add case" })[0] as HTMLElement);
    await screen.findByRole("dialog", { name: "Add test case" });
    await user.click(screen.getByTestId("dialog-backdrop"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: "Add case" })[0] as HTMLElement);
    const dialog = await screen.findByRole("dialog", { name: "Add test case" });
    await user.type(within(dialog).getByLabelText("Case name"), "Angry customer");
    await user.type(within(dialog).getByLabelText("Variable 1 value"), "refund");
    await user.click(screen.getByTestId("dialog-backdrop"));
    expect(screen.getByRole("dialog", { name: "Add test case" })).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Case name")).toHaveValue("Angry customer");
    // Cancel still discards deliberately.
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("starts an ad-hoc evaluation and navigates to it", async () => {
    const api = mockApi([...suiteRoutes(), route("POST", "/api/evals", () => json(evalDetail({ status: "queued" }), 202))]);
    const { user } = renderWithProviders(<SuiteDetailPage />, { route: `/suites/${ID.suite}`, path: "/suites/:suiteId" });
    await screen.findByRole("heading", { level: 1, name: "Greeting suite" });
    await user.click(screen.getByRole("radio", { name: "Ad-hoc" }));
    const panel = screen.getByRole("region", { name: "Run evaluation" });
    await user.click(within(panel).getByLabelText("User prompt"));
    await user.paste("Say hello to {{name}}");
    await user.click(within(panel).getByRole("checkbox", { name: "Demo Concise (offline)" }));
    expect(within(panel).getByText("1 case x 2 models = 2 / 200 calls")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Run evaluation" }));
    await waitFor(() => expect(currentLocation()).toBe(`/evals/${ID.eval}`));
    expect(api.callsTo("POST", "/api/evals")[0]?.body).toEqual({
      suite_id: ID.suite,
      system: null,
      prompt: "Say hello to {{name}}",
      models: ["claude-opus-5-5", "demo-concise"],
      temperature: null,
      max_tokens: null,
      thinking: false,
      judge_model: null,
    });
  });

  it("counts LLM judge calls against the evaluation call limit", async () => {
    const base = suiteDetail();
    const judgeCase = {
      ...base.cases[0]!,
      assertions: [
        { type: "llm_judge" as const, rubric: "Polite", threshold: 4, judge_model: null },
        { type: "llm_judge" as const, rubric: "Short", threshold: 4, judge_model: null },
      ],
    };
    mockApi([
      ...catalogRoutes(),
      route("GET", `/api/suites/${ID.suite}`, suiteDetail({ case_count: 1, cases: [judgeCase] })),
      route("GET", "/api/prompts", page([promptSummary()])),
      route("GET", `/api/prompts/${ID.prompt}/versions`, page([{ ...promptSummary().latest_version }])),
    ]);
    const { user } = renderWithProviders(<SuiteDetailPage />, { route: `/suites/${ID.suite}`, path: "/suites/:suiteId" });
    await screen.findByRole("heading", { level: 1, name: "Greeting suite" });
    const panel = screen.getByRole("region", { name: "Run evaluation" });
    await user.click(within(panel).getByRole("checkbox", { name: "Demo Concise (offline)" }));
    expect(within(panel).getByText("1 case x 2 models + 4 judge calls = 6 / 200 calls")).toBeInTheDocument();
  });

  it("uses the selected library prompt version", async () => {
    const api = mockApi([...suiteRoutes(), route("POST", "/api/evals", () => json(evalDetail(), 202))]);
    const { user } = renderWithProviders(<SuiteDetailPage />, { route: `/suites/${ID.suite}`, path: "/suites/:suiteId" });
    const panel = await screen.findByRole("region", { name: "Run evaluation" });
    await waitFor(() => expect(within(panel).getByRole("option", { name: "Summarizer" })).toBeInTheDocument());
    await user.selectOptions(within(panel).getByRole("combobox", { name: "Prompt" }), ID.prompt);
    await waitFor(() => expect(within(panel).getByRole("combobox", { name: "Version" })).toHaveValue(ID.version2));
    await user.click(within(panel).getByRole("button", { name: "Run evaluation" }));
    await waitFor(() => expect(api.callsTo("POST", "/api/evals")).toHaveLength(1));
    expect(api.callsTo("POST", "/api/evals")[0]?.body).toMatchObject({ prompt_version_id: ID.version2 });
  });
});

describe("EvalDetailPage", () => {
  it("polls while running and stops once completed", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const running: EvalRunDetail = evalDetail({
      status: "running",
      progress: { completed: 0, total: 1 },
      passed: 0,
      pass_rate: null,
      finished_at: null,
      results: [{ ...evalDetail().results[0]!, status: "pending", output: null, assertions: [], score: null }],
    });
    let calls = 0;
    const api = mockApi([
      ...catalogRoutes(),
      route("GET", `/api/evals/${ID.eval}`, () => {
        calls += 1;
        return json(calls < 2 ? running : evalDetail());
      }),
    ]);
    renderWithProviders(<EvalDetailPage />, { route: `/evals/${ID.eval}`, path: "/evals/:evalId" });
    const progress = await screen.findByRole("progressbar", { name: "Evaluation progress" });
    expect(progress).toHaveAttribute("aria-valuenow", "0");
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Says hello, Demo Concise \(offline\): Pending/ })).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(EVAL_POLL_INTERVAL_MS + 50);
    });
    await waitFor(() => expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "1"));
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
    const callsAfterCompletion = api.callsTo("GET", `/api/evals/${ID.eval}`).length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(EVAL_POLL_INTERVAL_MS * 3);
    });
    expect(api.callsTo("GET", `/api/evals/${ID.eval}`)).toHaveLength(callsAfterCompletion);
  });

  it("shows per-model summaries and opens a result drawer", async () => {
    mockApi([...catalogRoutes(), route("GET", `/api/evals/${ID.eval}`, evalDetail())]);
    const { user } = renderWithProviders(<EvalDetailPage />, { route: `/evals/${ID.eval}`, path: "/evals/:evalId" });
    await screen.findByRole("heading", { level: 1, name: "Greeting suite: Ad-hoc prompt" });
    expect(await screen.findByRole("heading", { level: 3, name: "Demo Concise (offline)" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Says hello, Demo Concise \(offline\): Passed, score 100%/ }));
    const drawer = await screen.findByRole("dialog", { name: "Says hello" });
    expect(within(drawer).getByText("Hello Ada!")).toBeInTheDocument();
    expect(within(drawer).getByText('Output contains "hello".')).toBeInTheDocument();
    expect(within(drawer).getByText("Ada")).toBeInTheDocument();
  });

  it("cancels a running evaluation", async () => {
    const running = evalDetail({ status: "running", progress: { completed: 0, total: 1 } });
    const api = mockApi([
      ...catalogRoutes(),
      route("GET", `/api/evals/${ID.eval}`, running),
      route("POST", `/api/evals/${ID.eval}/cancel`, { ...running, status: "cancelled" }),
    ]);
    const { user } = renderWithProviders(<EvalDetailPage />, { route: `/evals/${ID.eval}`, path: "/evals/:evalId" });
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(await screen.findByText("Evaluation cancelled")).toBeInTheDocument();
    expect(api.callsTo("POST", `/api/evals/${ID.eval}/cancel`)).toHaveLength(1);
  });
});

describe("EvalsPage", () => {
  it("lists runs and filters by status and suite", async () => {
    const api = mockApi([
      ...catalogRoutes(),
      route("GET", "/api/evals", page([{ ...evalDetail(), cases: undefined }])),
      route("GET", "/api/suites", page([{ ...suiteDetail(), cases: undefined, created_at: NOW }])),
    ]);
    const { user } = renderWithProviders(<EvalsPage />, { route: "/evals" });
    const table = await screen.findByRole("table", { name: "Evaluation runs" });
    expect(within(table).getByText("Ad-hoc prompt")).toBeInTheDocument();
    expect(within(table).getByText("100%")).toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "Status" }), "completed");
    await waitFor(() => expect(screen.getByRole("option", { name: "Greeting suite" })).toBeInTheDocument());
    await user.selectOptions(screen.getByRole("combobox", { name: "Suite" }), ID.suite);
    await waitFor(() => {
      const last = api.callsTo("GET", "/api/evals").at(-1);
      expect(last?.url.searchParams.get("status")).toBe("completed");
      expect(last?.url.searchParams.get("suite_id")).toBe(ID.suite);
    });
  });
});
