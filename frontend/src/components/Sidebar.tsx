import { Columns3, FlaskConical, History, Library, ListChecks, Settings, SquareTerminal } from "lucide-react";
import type { ReactNode } from "react";
import { NavLink } from "react-router";
import { cn } from "../lib/cn";

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
}

const ICON = "size-4 shrink-0";

const NAV_ITEMS: NavItem[] = [
  { to: "/playground", label: "Playground", icon: <SquareTerminal aria-hidden="true" className={ICON} /> },
  { to: "/compare", label: "Compare", icon: <Columns3 aria-hidden="true" className={ICON} /> },
  { to: "/library", label: "Library", icon: <Library aria-hidden="true" className={ICON} /> },
  { to: "/suites", label: "Test suites", icon: <ListChecks aria-hidden="true" className={ICON} /> },
  { to: "/evals", label: "Evaluations", icon: <FlaskConical aria-hidden="true" className={ICON} /> },
  { to: "/history", label: "History", icon: <History aria-hidden="true" className={ICON} /> },
  { to: "/settings", label: "Settings", icon: <Settings aria-hidden="true" className={ICON} /> },
];

/** Primary navigation links; `NavLink` sets `aria-current="page"` on the active one. */
export function NavList({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <ul className="space-y-0.5">
      {NAV_ITEMS.map((item) => (
        <li key={item.to}>
          <NavLink
            to={item.to}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium",
                isActive ? "bg-accent-soft text-accent-text" : "text-fg-muted hover:bg-surface-muted hover:text-fg",
              )
            }
          >
            {item.icon}
            {item.label}
          </NavLink>
        </li>
      ))}
    </ul>
  );
}

/** Product mark used in the sidebar and the mobile top bar (`compact` hides the name on narrow screens). */
export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2 font-semibold text-fg">
      <svg viewBox="0 0 32 32" aria-hidden="true" className="size-7 shrink-0">
        <rect width="32" height="32" rx="7" className="fill-accent" />
        <path
          d="M9 11.5 13.5 16 9 20.5"
          fill="none"
          stroke="#ffffff"
          strokeWidth="2.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path d="M16 21h7" fill="none" stroke="#ffffff" strokeWidth="2.6" strokeLinecap="round" />
      </svg>
      <span className={cn("leading-tight", compact && "sr-only sm:not-sr-only")}>
        Prompt Engineering
        <span className="block text-xs font-medium text-fg-muted">Studio</span>
      </span>
    </span>
  );
}

/** Desktop sidebar (hidden below 768 px, where the top bar's drawer takes over). */
export function Sidebar({ version }: { version: string | undefined }) {
  return (
    <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-line bg-surface md:flex">
      <div className="px-4 py-4">
        <Brand />
      </div>
      <nav aria-label="Main" className="flex-1 overflow-y-auto px-2 py-2">
        <NavList />
      </nav>
      <p className="px-4 py-3 text-xs text-fg-muted">{version ? `Version ${version}` : " "}</p>
    </aside>
  );
}
