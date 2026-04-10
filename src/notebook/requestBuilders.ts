import type { NotebookPanel } from "@jupyterlab/notebook";

import type {
  CommitMode,
  NotebookExtensionMetadata,
  SnapshotRequestPayload,
  SnapshotUserMetadata
} from "../types";
import { parseSnapshotRequestPayload } from "../types";

export function buildNotebookContextPayload(
  panel: NotebookPanel,
  metadata: NotebookExtensionMetadata,
  triggeringCellId: string | null
): SnapshotRequestPayload["notebook_context"] {
  const notebookPath = panel.context.path;
  const notebookName = panel.title.label;
  return {
    cell_ids: metadata.trigger_cell_ids,
    document_id: panel.id,
    kernel_id: panel.sessionContext.session?.kernel?.id ?? null,
    notebook_name: notebookName,
    notebook_path: notebookPath,
    triggering_cell_id: triggeringCellId
  };
}

export function buildManualSnapshotPayload(
  panel: NotebookPanel,
  metadata: NotebookExtensionMetadata,
  commitMode: CommitMode,
  userMetadata: SnapshotUserMetadata
): SnapshotRequestPayload {
  return parseSnapshotRequestPayload({
    commit_mode: commitMode,
    notebook_context: buildNotebookContextPayload(panel, metadata, null),
    source: "manual",
    user_metadata: userMetadata
  });
}

export function buildTriggerCellSnapshotPayload(
  panel: NotebookPanel,
  metadata: NotebookExtensionMetadata,
  commitMode: CommitMode,
  userMetadata: SnapshotUserMetadata,
  triggeringCellId: string
): SnapshotRequestPayload {
  return parseSnapshotRequestPayload({
    commit_mode: commitMode,
    notebook_context: buildNotebookContextPayload(
      panel,
      metadata,
      triggeringCellId
    ),
    source: "trigger_cell",
    user_metadata: userMetadata
  });
}
