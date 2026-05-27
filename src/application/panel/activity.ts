import type { ActivityRecord, SnapshotJobsResponse } from "../../types";

export interface ActivityRow {
  readonly jobId: string;
  readonly state: ActivityRecord["state"];
  readonly statusLabel: string;
  readonly message: string;
  /** A clickable LabArchives directory URL when the snapshot persisted (C-DEST-05). */
  readonly url: string | null;
  readonly isError: boolean;
}

export interface ActivitySection {
  readonly rows: readonly ActivityRow[];
  readonly emptyMessage: string | null;
}

const EMPTY_MESSAGE = "No snapshots yet. Your snapshot history will appear here.";

const STATE_LABELS: Record<ActivityRecord["state"], string> = {
  queued: "Queued",
  running: "Saving…",
  persisted: "Saved",
  failed: "Failed",
  abandoned: "Abandoned",
};

export function buildActivitySection(response: SnapshotJobsResponse): ActivitySection {
  const rows = response.jobs.map(toRow);
  return {
    rows,
    emptyMessage: rows.length === 0 ? EMPTY_MESSAGE : null,
  };
}

function toRow(record: ActivityRecord): ActivityRow {
  return {
    jobId: record.jobId,
    state: record.state,
    statusLabel: STATE_LABELS[record.state],
    message: record.displayMessage,
    url: record.directoryUrl,
    isError: record.state === "failed" || record.runOutcome === "error",
  };
}
