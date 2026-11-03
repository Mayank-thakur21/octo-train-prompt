import { TriangleAlert } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";

export interface ErrorBoundaryProps {
  children: ReactNode;
  /** `page` renders inside the layout; `root` fills the window. */
  scope?: "root" | "page";
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Catches render errors and shows "Something went wrong" with a Reload button.
 * One wraps the whole app; another wraps each route (reset by remounting on navigation).
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    return { error: error instanceof Error ? error : new Error("Unknown error") };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // Logged for developers only; the UI never shows stack traces.
    console.error("Unhandled UI error", error, info.componentStack);
  }

  private readonly reload = (): void => {
    window.location.reload();
  };

  private readonly retry = (): void => {
    this.setState({ error: null });
  };

  override render(): ReactNode {
    if (!this.state.error) return this.props.children;
    const root = this.props.scope !== "page";
    return (
      <div
        role="alert"
        className={
          root
            ? "flex min-h-dvh items-center justify-center bg-canvas p-6 text-fg"
            : "rounded-lg border border-line bg-surface p-6 text-fg"
        }
      >
        <div className="flex max-w-lg flex-col items-start gap-3">
          <TriangleAlert aria-hidden="true" className="size-8 text-warning" />
          <h2 className="text-xl font-semibold">Something went wrong</h2>
          <p className="text-sm text-fg-muted">
            The page hit an unexpected error. Reloading usually fixes it; your drafts are kept in this browser.
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={this.reload}
              className="inline-flex h-10 items-center rounded-md bg-accent px-4 text-sm font-medium text-accent-fg hover:bg-accent-hover"
            >
              Reload
            </button>
            {!root ? (
              <button
                type="button"
                onClick={this.retry}
                className="inline-flex h-10 items-center rounded-md border border-line-strong bg-surface px-4 text-sm font-medium text-fg hover:bg-surface-muted"
              >
                Try again
              </button>
            ) : null}
          </div>
        </div>
      </div>
    );
  }
}
