import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

let shouldThrow = true;

function Bomb() {
  if (shouldThrow) throw new Error("kaboom");
  return <p>Recovered</p>;
}

describe("ErrorBoundary", () => {
  it("shows the fallback with a Reload button and never the error stack", async () => {
    shouldThrow = true;
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const reload = vi.fn();
    vi.stubGlobal("location", { ...window.location, reload });
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong");
    expect(screen.queryByText(/kaboom/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reload" }));
    expect(reload).toHaveBeenCalled();
  });

  it("page-scoped boundaries can retry rendering", async () => {
    shouldThrow = true;
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    function Harness() {
      const [key] = useState(0);
      return (
        <ErrorBoundary key={key} scope="page">
          <Bomb />
        </ErrorBoundary>
      );
    }
    render(<Harness />);
    shouldThrow = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByText("Recovered")).toBeInTheDocument();
  });
});
