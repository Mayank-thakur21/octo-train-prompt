import { memo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "../lib/cn";
import { CopyButton } from "./CopyButton";

/** Plain text of a hast node (used to copy code blocks). */
function nodeText(node: unknown): string {
  if (typeof node !== "object" || node === null) return "";
  const record = node as { type?: string; value?: unknown; children?: unknown[] };
  if (record.type === "text" && typeof record.value === "string") return record.value;
  return Array.isArray(record.children) ? record.children.map(nodeText).join("") : "";
}

const components: Components = {
  // External links open in a new tab without access to this window.
  a: ({ node: _node, href, children, ...rest }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" {...rest}>
      {children}
    </a>
  ),
  // Images are not loaded (no tracking pixels, CSP stays strict); show them as links instead.
  img: ({ src, alt }) => {
    const url = typeof src === "string" ? src : "";
    const label = alt ? `Image: ${alt}` : "Image";
    return url ? (
      <a href={url} target="_blank" rel="noopener noreferrer">
        {label}
      </a>
    ) : (
      <span>{label}</span>
    );
  },
  pre: ({ node, children }) => {
    const code = nodeText(node).replace(/\n$/, "");
    return (
      <div className="group relative">
        <div className="absolute top-1.5 right-1.5 opacity-90">
          <CopyButton text={code} label="Copy code" variant="secondary" />
        </div>
        <pre>{children}</pre>
      </div>
    );
  },
};

export interface MarkdownProps {
  children: string;
  className?: string;
}

/**
 * Safe Markdown renderer for model output: GitHub-flavoured Markdown, raw HTML
 * skipped (`skipHtml`), dangerous URLs neutralised by the default `urlTransform`,
 * no `rehype-raw` and no `dangerouslySetInnerHTML`.
 */
export const Markdown = memo(function Markdown({ children, className }: MarkdownProps) {
  return (
    <div className={cn("markdown text-sm text-fg", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
});
