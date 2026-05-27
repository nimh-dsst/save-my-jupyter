import type { JobState } from "../../types";

// Status messages render as one of four visual kinds and are announced through
// an aria-live region in the panel (contract C-PANEL-10). Keeping the kind on
// the value (not inferred in the view) lets the controller decide tone once and
// the component render it consistently.

export type StatusKind = "info" | "success" | "warning" | "error";

export interface PanelStatus {
  readonly kind: StatusKind;
  readonly message: string;
}

export function info(message: string): PanelStatus {
  return { kind: "info", message };
}

export function success(message: string): PanelStatus {
  return { kind: "success", message };
}

export function warning(message: string): PanelStatus {
  return { kind: "warning", message };
}

export function error(message: string): PanelStatus {
  return { kind: "error", message };
}

/** Tone for a job's delivery state: persisted is success, failed is error,
 * abandoned is a warning, and queued/running are informational (C-SNAP-04/05/06). */
export function statusForJobState(
  state: JobState,
  message: string,
): PanelStatus {
  switch (state) {
    case "persisted":
      return success(message);
    case "failed":
      return error(message);
    case "abandoned":
      return warning(message);
    case "queued":
    case "running":
      return info(message);
  }
}
