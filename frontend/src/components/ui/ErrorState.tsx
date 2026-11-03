import { CircleAlert, KeyRound, RotateCcw } from "lucide-react";
import { Link, useInRouterContext } from "react-router";
import { ApiError } from "../../api/client";
import { errorDetailLines, errorMessage } from "../../lib/errors";
import { cn } from "../../lib/cn";
import { Button } from "./Button";
import { buttonClasses } from "./styles";

export interface ErrorStateProps {
  error: unknown;
  title?: string;
  onRetry?: () => void;
  className?: string;
  /** Compact inline variant for forms. */
  compact?: boolean;
}

/**
 * Error message from an `ApiError` envelope (never raw server bodies), with optional Retry.
 * A 401 also links to Settings, where the API key is entered: a page that failed to load because
 * the key is missing would otherwise leave the user with only a Retry that cannot succeed.
 */
export function ErrorState({ error, title, onRetry, className, compact = false }: ErrorStateProps) {
  const inRouter = useInRouterContext();
  const details = errorDetailLines(error);
  const code = error instanceof ApiError ? error.code : null;
  const needsApiKey = error instanceof ApiError && error.status === 401;
  const settingsClasses = buttonClasses("secondary", "sm");
  const settingsContent = (
    <>
      <KeyRound aria-hidden="true" className="size-4" />
      Open Settings
    </>
  );
  return (
    <div
      role="alert"
      className={cn(
        "flex gap-3 rounded-lg border border-danger/40 bg-danger-soft text-sm text-fg",
        compact ? "px-3 py-2" : "px-4 py-3",
        className,
      )}
    >
      <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-danger" />
      <div className="min-w-0 flex-1 space-y-1">
        {title ? <p className="font-semibold text-danger">{title}</p> : null}
        <p className="break-words">{errorMessage(error)}</p>
        {details.length > 0 ? (
          <ul className="list-disc space-y-0.5 pl-5 text-fg-muted">
            {details.map((line) => (
              <li key={line} className="break-words">
                {line}
              </li>
            ))}
          </ul>
        ) : null}
        {code && !compact ? <p className="font-mono text-xs text-fg-muted">Code: {code}</p> : null}
        {onRetry || needsApiKey ? (
          <div className="flex flex-wrap gap-2 pt-1">
            {needsApiKey ? (
              inRouter ? (
                <Link to="/settings" className={settingsClasses}>
                  {settingsContent}
                </Link>
              ) : (
                <a href="/settings" className={settingsClasses}>
                  {settingsContent}
                </a>
              )
            ) : null}
            {onRetry ? (
              <Button size="sm" icon={<RotateCcw aria-hidden="true" className="size-4" />} onClick={onRetry}>
                Retry
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
