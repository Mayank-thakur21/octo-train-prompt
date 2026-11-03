import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "../context/ToastProvider";
import { MemoryRouter } from "react-router";
import { Markdown } from "./Markdown";

function renderMarkdown(text: string) {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <Markdown>{text}</Markdown>
      </ToastProvider>
    </MemoryRouter>,
  );
}

describe("Markdown", () => {
  it("renders GitHub-flavoured Markdown", () => {
    const { container } = renderMarkdown("## Title\n\n- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n~~gone~~");
    expect(screen.getByRole("heading", { level: 2, name: "Title" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(container.querySelector("del")).toHaveTextContent("gone");
  });

  it("never renders raw HTML", () => {
    const { container } = renderMarkdown('Hello <img src="x" onerror="alert(1)"> <script>alert(2)</script><b>bold</b>');
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(container.innerHTML).not.toContain("onerror");
  });

  it("neutralises javascript: links and opens safe links in a new tab", () => {
    renderMarkdown("[bad](javascript:alert(1)) and [good](https://example.org)");
    const bad = screen.getByText("bad").closest("a");
    expect(bad?.getAttribute("href") ?? "").not.toContain("javascript");
    const good = screen.getByRole("link", { name: "good" });
    expect(good).toHaveAttribute("href", "https://example.org");
    expect(good).toHaveAttribute("target", "_blank");
    expect(good).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("shows images as links instead of loading them", () => {
    const { container } = renderMarkdown("![chart](https://example.org/c.png)");
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByRole("link", { name: "Image: chart" })).toHaveAttribute("href", "https://example.org/c.png");
  });

  it("renders code blocks in pre/code with a copy button", () => {
    const { container } = renderMarkdown("```js\nconst a = 1;\n```");
    expect(container.querySelector("pre > code")).toHaveTextContent("const a = 1;");
    expect(screen.getByRole("button", { name: "Copy code" })).toBeInTheDocument();
  });
});
