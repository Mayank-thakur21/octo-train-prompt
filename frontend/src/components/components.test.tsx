import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { VariableInfo } from "../api/types";
import { newAssertionDraft, type AssertionDraft } from "../lib/assertions";
import type { RunParamsValue } from "../lib/params";
import { MODELS, VERSION_DIFF } from "../test/fixtures";
import { AssertionEditor } from "./AssertionEditor";
import { DiffView } from "./DiffView";
import { ModelMultiSelect } from "./ModelMultiSelect";
import { ModelPicker } from "./ModelPicker";
import { RunParamsForm } from "./RunParamsForm";
import { VariablesForm } from "./VariablesForm";

describe("ModelPicker", () => {
  it("groups models by provider and disables unavailable ones", () => {
    render(<ModelPicker models={MODELS} value="claude-opus-5-5" onChange={() => undefined} />);
    const select = screen.getByRole("combobox", { name: "Model" });
    const groups = within(select).getAllByRole("group");
    expect(groups.map((group) => group.getAttribute("label"))).toEqual(["Anthropic", "OpenAI", "Google Gemini", "Demo (offline)"]);
    const haiku = within(select).getByRole("option", { name: "Claude Haiku 5.5 (no API key)" });
    expect(haiku).toBeDisabled();
    expect(within(select).getByRole("option", { name: "Claude Opus 5.5" })).toBeEnabled();
    expect(select).toHaveValue("claude-opus-5-5");
  });

  it("reports the chosen model", async () => {
    const onChange = vi.fn();
    render(<ModelPicker models={MODELS} value="claude-opus-5-5" onChange={onChange} />);
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Model" }), "demo-concise");
    expect(onChange).toHaveBeenCalledWith("demo-concise");
  });
});

describe("ModelMultiSelect", () => {
  it("disables unavailable models and stops at the maximum", async () => {
    function Harness() {
      const [value, setValue] = useState<string[]>([]);
      return <ModelMultiSelect models={MODELS} value={value} max={2} onChange={setValue} />;
    }
    render(<Harness />);
    expect(screen.getByRole("checkbox", { name: "GPT-5.5 (no API key)" })).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: "Claude Opus 5.5" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Demo Concise (offline)" }));
    expect(screen.getByText("2 of 2 selected (maximum reached)")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Demo Verbose (offline)" })).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: "Claude Opus 5.5" }));
    expect(screen.getByRole("checkbox", { name: "Demo Verbose (offline)" })).toBeEnabled();
  });
});

describe("VariablesForm", () => {
  const variables: VariableInfo[] = [
    { name: "name", default: null, required: true },
    { name: "tone", default: "friendly", required: false },
  ];

  it("renders one labelled field per variable with the default as placeholder", () => {
    render(<VariablesForm variables={variables} values={{}} onChange={() => undefined} />);
    const name = screen.getByLabelText("name");
    expect(name).toHaveAttribute("aria-required", "true");
    expect(screen.getByText("required")).toBeInTheDocument();
    expect(screen.getByLabelText("tone")).toHaveAttribute("placeholder", "friendly");
    expect(screen.getByText("optional")).toBeInTheDocument();
  });

  it("reports edits and flags missing variables", async () => {
    const onChange = vi.fn();
    render(<VariablesForm variables={variables} values={{}} missing={["name"]} onChange={onChange} />);
    await userEvent.type(screen.getByLabelText("name"), "A");
    expect(onChange).toHaveBeenCalledWith("name", "A");
    expect(screen.getByLabelText("name")).toHaveAccessibleDescription("A value is required.");
  });

  it("explains the syntax when there are no variables", () => {
    render(<VariablesForm variables={[]} values={{}} onChange={() => undefined} />);
    expect(screen.getByText(/No variables yet/)).toBeInTheDocument();
  });
});

describe("RunParamsForm", () => {
  function Harness({ initial, supportsTemperature = true }: { initial: RunParamsValue; supportsTemperature?: boolean }) {
    const [value, setValue] = useState(initial);
    return (
      <>
        <RunParamsForm
          value={value}
          onChange={setValue}
          supportsTemperature={supportsTemperature}
          supportsThinking
          thinkingAlwaysOn
          maxOutputTokens={1000}
          defaultMaxTokens={500}
        />
        <output data-testid="value">{JSON.stringify(value)}</output>
      </>
    );
  }

  it("toggles the model default temperature and keeps the slider value", async () => {
    render(<Harness initial={{ temperature: null, maxTokens: 500, thinking: false }} />);
    const useDefault = screen.getByRole("checkbox", { name: "Use model default" });
    expect(useDefault).toBeChecked();
    expect(screen.getByRole("slider", { name: "Temperature" })).toBeDisabled();
    await userEvent.click(useDefault);
    expect(screen.getByTestId("value")).toHaveTextContent('"temperature":1');
    expect(screen.getByRole("slider", { name: "Temperature" })).toBeEnabled();
  });

  it("shows unsupported temperature and always-on thinking hints", () => {
    render(<Harness initial={{ temperature: null, maxTokens: 500, thinking: false }} supportsTemperature={false} />);
    expect(screen.getByRole("slider", { name: "Temperature" })).toHaveAccessibleDescription("Not supported by this model");
    expect(screen.getByRole("switch", { name: "Show thinking" })).toHaveAccessibleDescription(
      "This model always thinks; the switch shows its thinking summary.",
    );
  });

  it("reports an out-of-range max tokens value without changing it on blur", async () => {
    render(<Harness initial={{ temperature: null, maxTokens: 500, thinking: false }} />);
    const input = screen.getByRole("spinbutton", { name: "Max tokens" });
    expect(input).toHaveAccessibleDescription("1 to 1,000");
    await userEvent.clear(input);
    await userEvent.type(input, "5000");
    // The error takes the hint's place, so the layout below does not move.
    expect(input).toHaveAccessibleDescription("Enter a value between 1 and 1,000.");
    expect(input).toHaveAttribute("aria-invalid", "true");
    await userEvent.tab();
    expect(input).toHaveValue(5000);
    expect(screen.getByTestId("value")).toHaveTextContent('"maxTokens":5000');
    expect(screen.getByText("Enter a value between 1 and 1,000.")).toBeInTheDocument();
  });
});

describe("AssertionEditor", () => {
  function Harness({ initial }: { initial: AssertionDraft }) {
    const [draft, setDraft] = useState(initial);
    return (
      <AssertionEditor draft={draft} index={0} onChange={setDraft} onRemove={() => undefined} canRemove={false} models={MODELS} />
    );
  }

  it("shows the fields of each assertion type", async () => {
    render(<Harness initial={newAssertionDraft("contains")} />);
    const typeSelect = screen.getByRole("combobox", { name: "Assertion 1 type" });
    expect(screen.getByLabelText("Expected text")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Case sensitive" })).not.toBeChecked();
    expect(screen.queryByRole("checkbox", { name: "Trim whitespace" })).not.toBeInTheDocument();

    await userEvent.selectOptions(typeSelect, "equals");
    expect(screen.getByRole("checkbox", { name: "Case sensitive" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Trim whitespace" })).toBeChecked();

    await userEvent.selectOptions(typeSelect, "regex");
    expect(screen.getByLabelText("Pattern")).toBeInTheDocument();
    for (const flag of ["i (ignore case)", "m (multiline)", "s (dot matches newline)"]) {
      expect(screen.getByRole("checkbox", { name: flag })).toBeInTheDocument();
    }

    await userEvent.selectOptions(typeSelect, "max_chars");
    expect(screen.getByRole("spinbutton", { name: "Maximum characters" })).toBeInTheDocument();

    await userEvent.selectOptions(typeSelect, "json_schema");
    expect(screen.getByLabelText("JSON schema")).toBeInTheDocument();

    await userEvent.selectOptions(typeSelect, "llm_judge");
    expect(screen.getByLabelText("Rubric")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Pass threshold" })).toHaveValue("4");
    expect(screen.getByRole("combobox", { name: "Judge model" })).toHaveValue("");

    await userEvent.selectOptions(typeSelect, "json_valid");
    expect(screen.getByText(/Passes when the output parses as JSON/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove assertion 1" })).toBeDisabled();
  });

  it("toggles regex flags", async () => {
    render(<Harness initial={{ ...newAssertionDraft("regex"), flags: "i" }} />);
    expect(screen.getByRole("checkbox", { name: "i (ignore case)" })).toBeChecked();
    await userEvent.click(screen.getByRole("checkbox", { name: "s (dot matches newline)" }));
    expect(screen.getByRole("checkbox", { name: "s (dot matches newline)" })).toBeChecked();
  });
});

describe("DiffView", () => {
  it("renders old and new sides with glyphs and screen-reader labels", () => {
    render(<DiffView title="User prompt" diff={VERSION_DIFF.prompt} fromLabel="v1" toLabel="v2" />);
    const region = screen.getByRole("region", { name: "User prompt diff" });
    expect(within(region).getByText("+1 added")).toBeInTheDocument();
    expect(within(region).getByText("-1 removed")).toBeInTheDocument();
    const rows = within(region).getAllByRole("row");
    // Header + one paired change row.
    expect(rows).toHaveLength(2);
    const cells = within(rows[1] as HTMLElement).getAllByRole("cell");
    expect(cells[1]).toHaveTextContent("removed: Summarize {{text}}");
    expect(cells[1]).toHaveTextContent("-");
    expect(cells[3]).toHaveTextContent("added: Summarize {{text}} in {{count|3}} bullets");
    expect(cells[0]).toHaveTextContent("1");
    // The wide table scrolls inside a positioned box so its sr-only text cannot widen the page.
    expect(within(region).getByRole("table").parentElement).toHaveClass("relative", "overflow-x-auto");
  });

  it("reports unchanged and empty texts", () => {
    render(<DiffView title="System prompt" diff={{ changed: false, added: 0, removed: 0, unified: "", lines: [] }} fromLabel="v1" toLabel="v2" />);
    expect(screen.getByText("No changes")).toBeInTheDocument();
    expect(screen.getByText("Empty in both versions.")).toBeInTheDocument();
  });
});
