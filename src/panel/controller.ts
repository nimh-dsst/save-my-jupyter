import { ApiClientError, type ApiClient } from "../apiClient";
import { buildActivitySection, type ActivitySection } from "../application/panel/activity";
import {
  buildReadinessSection,
  type ReadinessSection,
} from "../application/panel/readiness";
import { createSignal, patchSignal, type WritableSignal } from "../signals";
import { parseSnapshotJobsResponse } from "../types";

export interface PanelState {
  readonly readiness: ReadinessSection;
  readonly activity: ActivitySection;
  readonly notebookName: string | null;
  readonly status: string | null;
  readonly busy: boolean;
}

const UNAUTHENTICATED = {
  pendingRequestId: null,
  status: "unauthenticated" as const,
  storedNotebookNames: [] as string[],
  storedUserEmail: null,
  userEmail: null,
};

export function initialPanelState(): PanelState {
  return {
    readiness: buildReadinessSection(UNAUTHENTICATED),
    activity: buildActivitySection({ jobs: [] }),
    notebookName: null,
    status: null,
    busy: false,
  };
}

/** Owns the panel signal and drives it from the backend. Browser-only. */
export class SnapshotPanelController {
  readonly state: WritableSignal<PanelState> = createSignal(initialPanelState());

  constructor(private readonly api: ApiClient) {}

  setNotebookName(name: string | null): void {
    patchSignal(this.state, { notebookName: name });
  }

  async refreshAuth(): Promise<void> {
    try {
      const auth = await this.api.authStatus();
      patchSignal(this.state, { readiness: buildReadinessSection(auth) });
    } catch (error) {
      patchSignal(this.state, { status: describeError(error) });
    }
  }

  async refreshActivity(): Promise<void> {
    try {
      const jobs = parseSnapshotJobsResponse(await this.api.listJobs(20));
      patchSignal(this.state, { activity: buildActivitySection(jobs) });
    } catch (error) {
      patchSignal(this.state, { status: describeError(error) });
    }
  }

  async snapshot(body: unknown): Promise<void> {
    patchSignal(this.state, {
      busy: true,
      status: "Saving notebook, creating snapshot artifacts, and uploading to LabArchives.",
    });
    try {
      const result = await this.api.submitSnapshot(body);
      patchSignal(this.state, {
        status:
          result.status === "accepted"
            ? "Snapshot queued."
            : `Snapshot rejected: ${result.message}`,
      });
      await this.refreshActivity();
    } catch (error) {
      patchSignal(this.state, { status: describeError(error) });
    } finally {
      patchSignal(this.state, { busy: false });
    }
  }
}

function describeError(error: unknown): string {
  if (error instanceof ApiClientError) {
    return error.message;
  }
  return "The Save My Jupyter request failed.";
}
