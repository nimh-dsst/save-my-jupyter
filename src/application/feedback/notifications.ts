import type { PanelStatus } from "../panel/status";

export interface UiNotification {
  readonly autoClose: number;
  readonly kind: "error" | "success";
  readonly message: string;
}

export const TRIGGER_SUCCESS_NOTIFICATION = "Snapshot saved.";
export const TRIGGER_SUCCESS_AUTO_CLOSE_MS = 1000;
export const TRIGGER_FAILURE_NOTIFICATION =
  "Save My Jupyter trigger snapshot failed.";
export const TRIGGER_FAILURE_AUTO_CLOSE_MS = 4000;

export function triggerSnapshotNotification(
  status: PanelStatus | null,
): UiNotification | null {
  if (status?.kind === "success") {
    return {
      autoClose: TRIGGER_SUCCESS_AUTO_CLOSE_MS,
      kind: "success",
      message: TRIGGER_SUCCESS_NOTIFICATION,
    };
  }
  if (status?.kind === "error") {
    return {
      autoClose: TRIGGER_FAILURE_AUTO_CLOSE_MS,
      kind: "error",
      message: TRIGGER_FAILURE_NOTIFICATION,
    };
  }
  return null;
}
