import { FlaskRound, Menu, Moon, Sun } from "lucide-react";
import { useSettings } from "../context/settings";
import { useMeta, useReady } from "../hooks/queries";
import { cn } from "../lib/cn";
import { Brand } from "./Sidebar";
import { Badge } from "./ui/Badge";
import { IconButton } from "./ui/IconButton";

/** Backend status pill: "Online" while `/api/ready` succeeds (polled every 30 s), otherwise "Offline". */
function BackendStatus() {
  const ready = useReady();
  const state = ready.isSuccess ? "online" : ready.isError ? "offline" : "checking";
  const label = state === "online" ? "Online" : state === "offline" ? "Offline" : "Checking…";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        state === "online" && "border-success/40 bg-success-soft text-success",
        state === "offline" && "border-danger/40 bg-danger-soft text-danger",
        state === "checking" && "border-line bg-surface-muted text-fg-muted",
      )}
      title={state === "offline" ? "The backend is not reachable or not ready." : "Backend status"}
    >
      <span
        aria-hidden="true"
        className={cn(
          "size-2 rounded-full",
          state === "online" ? "bg-success" : state === "offline" ? "bg-danger" : "bg-fg-muted",
        )}
      />
      <span>
        <span className="sr-only">Backend status: </span>
        {label}
      </span>
    </span>
  );
}

/** Top bar: menu button + brand on small screens, backend status, demo badge and a theme toggle. */
export function TopBar({ onOpenMenu, menuOpen }: { onOpenMenu: () => void; menuOpen: boolean }) {
  const meta = useMeta();
  const { resolvedTheme, setTheme } = useSettings();
  const nextTheme = resolvedTheme === "dark" ? "light" : "dark";

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-line bg-surface/95 px-4 backdrop-blur sm:gap-3 md:px-8">
      <IconButton
        label="Open navigation menu"
        aria-expanded={menuOpen}
        aria-haspopup="dialog"
        className="md:hidden"
        icon={<Menu aria-hidden="true" className="size-5" />}
        onClick={onOpenMenu}
      />
      <div className="min-w-0 md:hidden">
        <Brand compact />
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-1.5 sm:gap-2">
        {meta.data?.demo_mode ? (
          <Badge tone="warning" icon={<FlaskRound aria-hidden="true" className="size-3.5" />} title="No provider API key is configured; offline demo models answer.">
            Demo mode
          </Badge>
        ) : null}
        <BackendStatus />
        <IconButton
          label={`Switch to ${nextTheme} theme`}
          icon={
            resolvedTheme === "dark" ? <Sun aria-hidden="true" className="size-4" /> : <Moon aria-hidden="true" className="size-4" />
          }
          onClick={() => setTheme(nextTheme)}
        />
      </div>
    </header>
  );
}
