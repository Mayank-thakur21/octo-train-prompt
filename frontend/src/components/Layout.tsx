import { Suspense, useEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router";
import { useMeta } from "../hooks/queries";
import { focusPageHeading } from "../lib/routeFocus";
import { ErrorBoundary } from "./ErrorBoundary";
import { NavList, Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { Dialog } from "./ui/Dialog";
import { PageSkeleton } from "./ui/Skeleton";

/**
 * App shell: skip link, sidebar (desktop) or top bar with drawer (< 768 px),
 * and the routed page inside its own error boundary and suspense fallback.
 */
export function Layout() {
  const location = useLocation();
  const meta = useMeta();
  const [menuOpen, setMenuOpen] = useState(false);
  const previousPath = useRef<string | null>(null);

  // Move focus to the new page's heading after client-side navigation (not on first load).
  useEffect(() => {
    if (previousPath.current !== null && previousPath.current !== location.pathname) focusPageHeading();
    previousPath.current = location.pathname;
  }, [location.pathname]);

  return (
    <div className="min-h-dvh md:flex">
      <a
        href="#main"
        className="sr-only z-[70] rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-fg focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to content
      </a>
      <Sidebar version={meta.data?.version} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar menuOpen={menuOpen} onOpenMenu={() => setMenuOpen(true)} />
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-7xl min-w-0 flex-1 px-4 py-6 md:px-8">
          <ErrorBoundary key={location.pathname} scope="page">
            <Suspense fallback={<PageSkeleton />}>
              <Outlet />
            </Suspense>
          </ErrorBoundary>
        </main>
      </div>
      <Dialog open={menuOpen} onClose={() => setMenuOpen(false)} title="Navigation" variant="left">
        <nav aria-label="Main">
          <NavList onNavigate={() => setMenuOpen(false)} />
        </nav>
      </Dialog>
    </div>
  );
}
