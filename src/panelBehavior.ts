import type { AuthState } from "./types";

export interface SnapshotAvailability {
  enabled: boolean;
  message: string;
}

export function requiresPanelSetup(auth: AuthState): boolean {
  return auth.status !== "authenticated";
}

export function getSnapshotAvailability(
  auth: AuthState,
  notebookPath: string | null,
  isBusy: boolean
): SnapshotAvailability {
  if (notebookPath === null) {
    return {
      enabled: false,
      message: "Open a notebook to configure and create snapshots."
    };
  }

  if (isBusy) {
    return {
      enabled: false,
      message: "Save My Jupyter is working on the current request."
    };
  }

  if (requiresPanelSetup(auth)) {
    return {
      enabled: false,
      message: "Connect LabArchives to enable snapshot creation."
    };
  }

  return {
    enabled: true,
    message: "Ready to create a snapshot for this notebook."
  };
}
