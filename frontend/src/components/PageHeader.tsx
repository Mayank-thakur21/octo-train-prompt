import { useEffect, useRef, type ReactNode } from "react";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { consumePendingHeadingFocus } from "../lib/routeFocus";

export interface PageHeaderProps {
  /** Page heading; also used for the document title unless `documentTitle` is given. */
  title: string;
  documentTitle?: string;
  description?: ReactNode;
  actions?: ReactNode;
  /** Small line above the title, e.g. breadcrumbs. */
  eyebrow?: ReactNode;
}

/**
 * Page `<h1>` plus actions. Sets `document.title` and receives focus after
 * client-side navigation (see `lib/routeFocus.ts`).
 */
export function PageHeader({ title, documentTitle, description, actions, eyebrow }: PageHeaderProps) {
  useDocumentTitle(documentTitle ?? title);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (consumePendingHeadingFocus()) headingRef.current?.focus();
  }, []);

  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      {/* Long unbroken names (snake_case, URLs) wrap anywhere instead of widening the page. */}
      <div className="min-w-0 max-w-full [overflow-wrap:anywhere]">
        {eyebrow ? <div className="mb-1 min-w-0 text-sm text-fg-muted">{eyebrow}</div> : null}
        <h1 ref={headingRef} tabIndex={-1} className="text-2xl font-semibold tracking-tight text-fg">
          {title}
        </h1>
        {description ? <p className="mt-1 max-w-3xl text-sm text-fg-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
