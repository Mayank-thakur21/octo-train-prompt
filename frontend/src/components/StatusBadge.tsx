import { Ban, CircleCheck, CircleDashed, CircleX, Clock, LoaderCircle, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import type { CaseResultStatus, EvalStatus, HistoryStatus } from "../api/types";
import { Badge, type BadgeTone } from "./ui/Badge";

export type AnyStatus = HistoryStatus | EvalStatus | CaseResultStatus;

const ICON = "size-3.5";

const STATUS: Record<AnyStatus, { label: string; tone: BadgeTone; icon: ReactNode }> = {
  success: { label: "Success", tone: "success", icon: <CircleCheck aria-hidden="true" className={ICON} /> },
  passed: { label: "Passed", tone: "success", icon: <CircleCheck aria-hidden="true" className={ICON} /> },
  completed: { label: "Completed", tone: "success", icon: <CircleCheck aria-hidden="true" className={ICON} /> },
  error: { label: "Error", tone: "danger", icon: <TriangleAlert aria-hidden="true" className={ICON} /> },
  failed: { label: "Failed", tone: "danger", icon: <CircleX aria-hidden="true" className={ICON} /> },
  cancelled: { label: "Cancelled", tone: "neutral", icon: <Ban aria-hidden="true" className={ICON} /> },
  queued: { label: "Queued", tone: "info", icon: <Clock aria-hidden="true" className={ICON} /> },
  running: {
    label: "Running",
    tone: "info",
    icon: <LoaderCircle aria-hidden="true" className={`${ICON} animate-spin`} />,
  },
  pending: { label: "Pending", tone: "neutral", icon: <CircleDashed aria-hidden="true" className={ICON} /> },
};

/** Status pill with icon and text (never color alone). */
export function StatusBadge({ status, className }: { status: AnyStatus; className?: string }) {
  const config = STATUS[status];
  return (
    <Badge tone={config.tone} icon={config.icon} className={className}>
      {config.label}
    </Badge>
  );
}
