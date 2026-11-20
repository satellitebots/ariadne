export const PHASES = ["Brief", "Plan", "Sign-off", "Execute", "QA", "Report"] as const;

export interface PhaseInfo {
  current: number;
  failed: boolean;
  complete: boolean;
}

export function phaseInfo(status: string): PhaseInfo {
  switch (status) {
    case "new":
    case "awaiting_gates":
      return { current: 0, failed: false, complete: false };
    case "approved":
    case "planning":
      return { current: 1, failed: false, complete: false };
    case "awaiting_signoff":
      return { current: 2, failed: false, complete: false };
    case "needs_attention":
      return { current: 3, failed: false, complete: false };
    case "executing":
      return { current: 3, failed: false, complete: false };
    case "done":
      return { current: 5, failed: false, complete: true };
    case "failed":
      return { current: 4, failed: true, complete: false };
    case "rejected":
      return { current: 2, failed: true, complete: false };
    case "cancelled":
      return { current: 5, failed: true, complete: true };
    case "timed_out":
      return { current: 5, failed: true, complete: true };
    default:
      return { current: 0, failed: false, complete: false };
  }
}

export const STATUS_LABEL: Record<string, string> = {
  new: "queued",
  awaiting_gates: "waiting for check gates",
  awaiting_signoff: "waiting for you",
  approved: "approved",
  planning: "working",
  executing: "working",
  needs_attention: "needs a decision",
  done: "done",
  failed: "failed",
  cancelled: "cancelled",
  rejected: "rejected",
  timed_out: "out of time",
};

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}