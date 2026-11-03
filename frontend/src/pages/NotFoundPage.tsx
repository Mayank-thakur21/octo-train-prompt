import { Compass } from "lucide-react";
import { useLocation } from "react-router";
import { PageHeader } from "../components/PageHeader";
import { ButtonLink } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";

/** Fallback for unknown routes. */
export default function NotFoundPage() {
  const location = useLocation();
  return (
    <>
      <PageHeader title="Page not found" />
      <EmptyState
        icon={<Compass aria-hidden="true" className="size-8" />}
        title="There is nothing at this address"
        description={`No page matches ${location.pathname}.`}
        action={
          <ButtonLink to="/playground" variant="primary">
            Go to the Playground
          </ButtonLink>
        }
      />
    </>
  );
}
