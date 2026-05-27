import type { ActivityRecord, SnapshotJobsResponse } from "../../types";

export interface ActivityRow {
  readonly jobId: string;
  readonly state: ActivityRecord["state"];
  readonly statusLabel: string;
  readonly message: string;
  readonly phaseItems: readonly ActivityPhase[];
  readonly phaseLabels: readonly string[];
  readonly runOutcomeLabel: string | null;
  /** A clickable LabArchives directory URL when the snapshot persisted (C-DEST-05). */
  readonly url: string | null;
  readonly isError: boolean;
}

export interface ActivityPhase {
  readonly label: string;
  readonly status: "pending" | "current";
}

export interface ActivitySection {
  readonly rows: readonly ActivityRow[];
  readonly totalRows: number;
  readonly overflowMessage: string | null;
  readonly emptyMessage: string | null;
}

const EMPTY_MESSAGE =
  "No snapshots yet. Your snapshot history will appear here.";
const VISIBLE_ACTIVITY_LIMIT = 5;

const STATE_LABELS: Record<ActivityRecord["state"], string> = {
  queued: "Queued",
  running: "Saving...",
  persisted: "Saved",
  failed: "Failed",
  abandoned: "Abandoned",
};

export function buildActivitySection(
  response: SnapshotJobsResponse,
): ActivitySection {
  const totalRows = response.jobs.length;
  const rows = response.jobs.slice(0, VISIBLE_ACTIVITY_LIMIT).map(toRow);
  return {
    rows,
    totalRows,
    overflowMessage:
      totalRows > rows.length
        ? `Showing ${String(rows.length)} most recent of ${String(totalRows)} runs.`
        : null,
    emptyMessage: rows.length === 0 ? EMPTY_MESSAGE : null,
  };
}

function toRow(record: ActivityRecord): ActivityRow {
  const phases = phaseItems(record.state);
  return {
    jobId: record.jobId,
    state: record.state,
    statusLabel: STATE_LABELS[record.state],
    message: record.displayMessage,
    phaseItems: phases,
    phaseLabels: phases.map((phase) => phase.label),
    runOutcomeLabel: runOutcomeLabel(record),
    url: record.directoryUrl,
    isError: record.state === "failed",
  };
}

function phaseItems(state: ActivityRecord["state"]): readonly ActivityPhase[] {
  if (state !== "queued" && state !== "running") {
    return [];
  }
  const status = state === "running" ? "current" : "pending";
  return [
    "Saving notebook",
    "Capturing artifacts",
    "Committing changes",
    "Uploading to LabArchives",
  ].map((label) => ({ label, status }));
}

function runOutcomeLabel(record: ActivityRecord): string | null {
  if (record.runOutcome === "error") {
    return "Run ended with errors";
  }
  return null;
}
