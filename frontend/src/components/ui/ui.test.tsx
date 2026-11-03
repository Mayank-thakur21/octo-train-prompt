import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { useToast } from "../../context/toast";
import { ToastProvider } from "../../context/ToastProvider";
import { Dialog } from "./Dialog";
import { ErrorState } from "./ErrorState";
import { HorizontalScroll } from "./HorizontalScroll";
import { ScrollableText } from "./ScrollableText";
import { Pagination } from "./Pagination";
import { Tabs } from "./Tabs";

describe("Dialog", () => {
  function Harness() {
    const [open, setOpen] = useState(false);
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>
          Open
        </button>
        <Dialog open={open} onClose={() => setOpen(false)} title="Edit thing" footer={<button type="button">Save</button>}>
          <input aria-label="First field" />
          <input aria-label="Second field" />
        </Dialog>
      </>
    );
  }

  it("is modal, focuses the first field, traps Tab, closes on Escape and restores focus", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open" });
    await user.click(opener);
    const dialog = screen.getByRole("dialog", { name: "Edit thing" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByLabelText("First field")).toHaveFocus();

    await user.tab();
    expect(screen.getByLabelText("Second field")).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Save" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Close dialog" })).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "Save" })).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });
});

describe("HorizontalScroll", () => {
  it("scrolls its content and is the containing block for sr-only descendants", () => {
    render(
      <HorizontalScroll className="rounded-lg" data-testid="scroller">
        <table>
          <caption className="sr-only">Wide table</caption>
          <tbody>
            <tr>
              <td>cell</td>
            </tr>
          </tbody>
        </table>
      </HorizontalScroll>,
    );
    const scroller = screen.getByTestId("scroller");
    // `relative` keeps absolutely positioned sr-only text inside the scroll box instead of
    // letting it widen the page on narrow screens.
    expect(scroller).toHaveClass("relative", "overflow-x-auto", "rounded-lg");
    expect(screen.getByRole("table", { name: "Wide table" }).parentElement).toBe(scroller);
  });
});

describe("HorizontalScroll keyboard access", () => {
  function stubLayout(scrollWidth: number, clientWidth: number) {
    vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(scrollWidth);
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(clientWidth);
    // Report once on observe, like a real ResizeObserver.
    class ImmediateResizeObserver {
      private readonly callback: () => void;
      constructor(callback: () => void) {
        this.callback = callback;
      }
      observe() {
        this.callback();
      }
      disconnect() {}
    }
    vi.stubGlobal("ResizeObserver", ImmediateResizeObserver);
  }

  it("becomes a focusable, labelled region when its content overflows", () => {
    stubLayout(576, 292);
    render(
      <HorizontalScroll label="System prompt diff">
        <table>
          <tbody>
            <tr>
              <td>wide</td>
            </tr>
          </tbody>
        </table>
      </HorizontalScroll>,
    );
    const region = screen.getByRole("region", { name: "System prompt diff, scrollable" });
    expect(region).toHaveAttribute("tabindex", "0");
  });

  it("makes a tall template box a focusable region and wraps long words", () => {
    stubLayout(292, 292);
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(900);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(320);
    render(<ScrollableText label="User prompt" text={"line\n".repeat(80)} />);
    const region = screen.getByRole("region", { name: "User prompt, scrollable" });
    expect(region).toHaveAttribute("tabindex", "0");
    expect(region).toHaveClass("[overflow-wrap:anywhere]");
  });

  it("stays out of the tab order when everything fits", () => {
    stubLayout(292, 292);
    render(
      <HorizontalScroll label="System prompt diff" data-testid="fits">
        <p>narrow</p>
      </HorizontalScroll>,
    );
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
    expect(screen.getByTestId("fits")).not.toHaveAttribute("tabindex");
  });
});

describe("Tabs", () => {
  it("switches panels with the mouse and arrow keys", async () => {
    const user = userEvent.setup();
    render(
      <Tabs
        label="Views"
        items={[
          { id: "a", label: "Alpha", content: <p>Panel A</p> },
          { id: "b", label: "Beta", content: <p>Panel B</p> },
        ]}
      />,
    );
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Panel A");
    await user.click(screen.getByRole("tab", { name: "Alpha" }));
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Beta" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Beta" })).toHaveFocus();
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Panel B");
  });
});

describe("Pagination", () => {
  it("summarises the range and pages", async () => {
    const onChange = vi.fn();
    render(<Pagination total={45} limit={20} offset={20} onChange={onChange} />);
    expect(screen.getByText("Showing 21–40 of 45")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onChange).toHaveBeenCalledWith(40);
    await userEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(onChange).toHaveBeenCalledWith(0);
  });

  it("is hidden when everything fits", () => {
    const { container } = render(<Pagination total={3} limit={20} offset={0} onChange={() => undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ErrorState", () => {
  it("links to Settings when the API key is missing or invalid", async () => {
    const onRetry = vi.fn();
    render(
      <MemoryRouter>
        <ErrorState error={new ApiError(401, "unauthorized", "A valid API key is required.")} onRetry={onRetry} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("A valid API key is required.");
    expect(screen.getByRole("link", { name: "Open Settings" })).toHaveAttribute("href", "/settings");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("uses a plain link to Settings outside a router", () => {
    render(<ErrorState error={new ApiError(401, "unauthorized", "A valid API key is required.")} />);
    expect(screen.getByRole("link", { name: "Open Settings" })).toHaveAttribute("href", "/settings");
  });

  it("does not offer Settings for other errors", () => {
    render(<ErrorState error={new ApiError(500, "internal_error", "Unexpected server error.")} />);
    expect(screen.queryByRole("link", { name: "Open Settings" })).not.toBeInTheDocument();
  });

  it("shows the envelope message, detail lines and Retry", async () => {
    const onRetry = vi.fn();
    render(
      <ErrorState
        error={new ApiError(422, "missing_variables", "Missing template variables.", { missing: ["name", "tone"] })}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Missing template variables.");
    expect(screen.getByText("Missing variables: name, tone")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("lists validation errors without the location prefix", () => {
    render(
      <ErrorState
        error={new ApiError(422, "validation_error", "Request validation failed.", {
          errors: [{ loc: ["body", "prompt"], msg: "Field required", type: "missing" }],
        })}
      />,
    );
    expect(screen.getByText("prompt: Field required")).toBeInTheDocument();
  });
});

describe("ToastProvider", () => {
  function Trigger() {
    const { toast } = useToast();
    return (
      <>
        <button type="button" onClick={() => toast({ tone: "success", title: `Saved ${Math.random()}` })}>
          Success
        </button>
        <button type="button" onClick={() => toast({ id: "e", tone: "error", title: "Broken" })}>
          Error
        </button>
      </>
    );
  }

  it("uses status/alert live regions, caps visible toasts and auto-dismisses", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
    render(
      <MemoryRouter>
        <ToastProvider>
          <Trigger />
        </ToastProvider>
      </MemoryRouter>,
    );
    for (let i = 0; i < 5; i += 1) await user.click(screen.getByRole("button", { name: "Success" }));
    expect(screen.getByRole("status").querySelectorAll("p.font-medium")).toHaveLength(4);
    await user.click(screen.getByRole("button", { name: "Error" }));
    await user.click(screen.getByRole("button", { name: "Error" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Broken");
    expect(screen.getAllByText("Broken")).toHaveLength(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5100);
    });
    expect(screen.getByRole("status").querySelectorAll("p.font-medium")).toHaveLength(0);
    expect(screen.getByRole("alert")).toHaveTextContent("Broken");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
  });

  it("dismisses on the close button", async () => {
    render(
      <MemoryRouter>
        <ToastProvider>
          <Trigger />
        </ToastProvider>
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Error" }));
    await userEvent.click(screen.getByRole("button", { name: "Dismiss notification" }));
    expect(screen.queryByText("Broken")).not.toBeInTheDocument();
  });
});
