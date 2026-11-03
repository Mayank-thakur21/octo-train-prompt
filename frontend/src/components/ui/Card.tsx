import { useId, type ReactNode } from "react";
import { cn } from "../../lib/cn";

export interface CardProps {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
  /** Replaces the default body padding (`p-4`). */
  bodyClassName?: string;
  /** Heading level for the title (defaults to h2). */
  headingLevel?: 2 | 3;
}

/** Bordered surface. With a title it becomes a labelled `<section>` (a navigable region). */
export function Card({ title, description, actions, children, className, bodyClassName, headingLevel = 2 }: CardProps) {
  const titleId = useId();
  const Heading = headingLevel === 2 ? "h2" : "h3";
  const hasHeader = title !== undefined || actions !== undefined;
  const content = (
    <>
      {hasHeader ? (
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0 [overflow-wrap:anywhere]">
            {title !== undefined ? (
              <Heading id={titleId} className="text-base font-semibold text-fg">
                {title}
              </Heading>
            ) : null}
            {description ? <p className="mt-0.5 text-sm text-fg-muted">{description}</p> : null}
          </div>
          {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
        </div>
      ) : null}
      <div className={bodyClassName ?? "p-4"}>{children}</div>
    </>
  );
  const classes = cn("min-w-0 rounded-lg border border-line bg-surface shadow-xs", className);
  return title !== undefined ? (
    <section aria-labelledby={titleId} className={classes}>
      {content}
    </section>
  ) : (
    <div className={classes}>{content}</div>
  );
}
