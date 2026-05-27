import type { CommitMode, RunOutcome } from "../types";

export interface SnapshotRequestInput {
  readonly source: "manual" | "trigger_cell";
  readonly notebookPath: string;
  readonly notebookName: string;
  readonly documentId?: string | null;
  readonly kernelId?: string | null;
  readonly triggeringCellId?: string | null;
  readonly triggeredCellIds?: readonly string[];
  readonly cellExecutionCount?: number | null;
  readonly tags?: readonly string[];
  readonly runLabel?: string | null;
  readonly notes?: string | null;
  readonly extraFields?: Record<string, string>;
  readonly commitMode?: CommitMode | null;
  readonly runOutcome?: RunOutcome | null;
  readonly watchedPaths?: readonly string[];
  readonly clientTimestamp?: string;
  readonly notebookContent?: unknown;
}

/** Build the JSON body for POST /snapshot. Keys are snake_case to match the
 * backend request parser (transport/parsers.py); omitted fields fall back to
 * backend defaults. */
export function buildSnapshotRequestBody(
  input: SnapshotRequestInput,
): Record<string, unknown> {
  const body: Record<string, unknown> = {
    source: input.source,
    notebook_context: {
      notebook_path: input.notebookPath,
      notebook_name: input.notebookName,
      document_id: input.documentId ?? null,
      kernel_id: input.kernelId ?? null,
      triggering_cell_id: input.triggeringCellId ?? null,
      triggered_cell_ids: [...(input.triggeredCellIds ?? [])],
      cell_execution_count: input.cellExecutionCount ?? null,
    },
    user_metadata: {
      tags: [...(input.tags ?? [])],
      run_label: input.runLabel ?? null,
      notes: input.notes ?? null,
      extra_fields: { ...(input.extraFields ?? {}) },
    },
  };
  if (input.watchedPaths !== undefined && input.watchedPaths.length > 0) {
    body["watched_paths"] = [...input.watchedPaths];
  }
  if (input.commitMode != null) {
    body["commit_mode"] = input.commitMode;
  }
  if (input.runOutcome != null) {
    body["run_outcome"] = input.runOutcome;
  }
  if (input.clientTimestamp !== undefined) {
    body["client_timestamp"] = input.clientTimestamp;
  }
  if (input.notebookContent !== undefined) {
    body["notebook_content"] = input.notebookContent;
  }
  return body;
}
