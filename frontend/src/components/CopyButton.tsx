import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";
import { useToast } from "../context/toast";
import { copyText } from "../lib/clipboard";
import { Button } from "./ui/Button";
import type { ButtonSize, ButtonVariant } from "./ui/styles";

export interface CopyButtonProps {
  text: string;
  /** Visible label and accessible name, e.g. "Copy output". */
  label?: string;
  size?: ButtonSize;
  variant?: ButtonVariant;
  disabled?: boolean;
  className?: string;
}

/** Copies text to the clipboard (also over plain HTTP) and confirms with a check mark for two seconds. */
export function CopyButton({
  text,
  label = "Copy",
  size = "sm",
  variant = "secondary",
  disabled = false,
  className,
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const { toast } = useToast();

  useEffect(() => {
    if (!copied) return undefined;
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const copy = async () => {
    if (await copyText(text)) {
      setCopied(true);
    } else {
      toast({ tone: "error", title: "Copy failed", description: "Select the text and copy it with your keyboard instead." });
    }
  };

  return (
    <Button
      size={size}
      variant={variant}
      disabled={disabled}
      className={className}
      aria-label={label}
      icon={
        copied ? <Check aria-hidden="true" className="size-4 text-success" /> : <Copy aria-hidden="true" className="size-4" />
      }
      onClick={() => void copy()}
    >
      <span aria-hidden="true">{copied ? "Copied" : label}</span>
      <span className="sr-only" aria-live="polite">
        {copied ? "Copied to clipboard" : ""}
      </span>
    </Button>
  );
}
