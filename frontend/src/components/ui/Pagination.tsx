import { ChevronLeft, ChevronRight } from "lucide-react";
import { formatNumber } from "../../lib/format";
import { Button } from "./Button";

export interface PaginationProps {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
  /** Accessible name of the navigation landmark. */
  label?: string;
}

/** Previous/Next pager with a "Showing x–y of z" summary. Hidden when everything fits on one page. */
export function Pagination({ total, limit, offset, onChange, label = "Pagination" }: PaginationProps) {
  if (total <= limit && offset === 0) return null;
  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + limit, total);
  return (
    <nav aria-label={label} className="flex flex-wrap items-center justify-between gap-3 pt-3">
      <p className="text-sm text-fg-muted">
        Showing {formatNumber(start)}–{formatNumber(end)} of {formatNumber(total)}
      </p>
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={offset === 0}
          icon={<ChevronLeft aria-hidden="true" className="size-4" />}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          Previous
        </Button>
        <Button size="sm" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>
          Next
          <ChevronRight aria-hidden="true" className="size-4" />
        </Button>
      </div>
    </nav>
  );
}
