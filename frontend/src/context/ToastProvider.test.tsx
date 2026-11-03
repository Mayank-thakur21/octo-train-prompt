import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { useToast } from "./toast";
import { ToastProvider } from "./ToastProvider";

function Trigger() {
  const { toast } = useToast();
  return (
    <button
      type="button"
      onClick={() => toast({ tone: "success", title: "Saved", action: { label: "Open in Library", to: "/library/1" } })}
    >
      Save
    </button>
  );
}

function renderToasts() {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) });
  render(
    <MemoryRouter>
      <ToastProvider>
        <main id="main" tabIndex={-1}>
          <Trigger />
          <button type="button">Elsewhere</button>
        </main>
      </ToastProvider>
    </MemoryRouter>,
  );
  return user;
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

async function focus(element: HTMLElement) {
  await act(async () => {
    element.focus();
    await Promise.resolve();
  });
}

describe("ToastProvider", () => {
  it("keeps a toast while focus is inside it and dismisses it after focus leaves", async () => {
    const user = renderToasts();
    await user.click(screen.getByRole("button", { name: "Save" }));
    const link = screen.getByRole("link", { name: "Open in Library" });
    await focus(link);
    await advance(12_000);
    expect(screen.getByRole("link", { name: "Open in Library" })).toHaveFocus();

    await focus(screen.getByRole("button", { name: "Elsewhere" }));
    await advance(4_000);
    expect(screen.getByText("Saved")).toBeInTheDocument();
    await advance(1_500);
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
  });

  it("pauses while hovered", async () => {
    const user = renderToasts();
    await user.click(screen.getByRole("button", { name: "Save" }));
    fireEvent.mouseEnter(screen.getByTestId("toast"));
    await advance(12_000);
    expect(screen.getByText("Saved")).toBeInTheDocument();
    fireEvent.mouseLeave(screen.getByTestId("toast"));
    await advance(5_500);
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
  });

  it("returns focus to where it came from when a focused toast is dismissed", async () => {
    const user = renderToasts();
    const save = screen.getByRole("button", { name: "Save" });
    await user.click(save);
    await user.tab(); // Elsewhere
    await user.tab(); // into the toast: its link
    expect(screen.getByRole("link", { name: "Open in Library" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Dismiss notification" }));
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Elsewhere" })).toHaveFocus();
  });
});
