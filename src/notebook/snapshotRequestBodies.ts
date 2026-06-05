import type { Cell } from "@jupyterlab/cells";
import { PathExt } from "@jupyterlab/coreutils";
import type { NotebookPanel } from "@jupyterlab/notebook";

import { mergeTags, parseDirectives } from "../application/directives";
import type { SnapshotRequestOptions } from "../panel/controller";
import type { RunOutcome } from "../types";

import {
  collectDynamicKernelMetadata,
  type DynamicKernelMetadata,
} from "./kernelMetadata";
import { readNotebookWatchedPaths } from "./notebookState";
import { buildSnapshotRequestBody } from "./requestBuilders";
import {
  firstNonBlankSourceLine,
  notebookCellSources,
} from "./sourceText";

const EMPTY_DYNAMIC_METADATA: DynamicKernelMetadata = {
  runLabel: null,
  tags: [],
};

export function buildManualBody(
  panel: NotebookPanel,
  options: SnapshotRequestOptions,
  dynamicMetadata: DynamicKernelMetadata = EMPTY_DYNAMIC_METADATA,
): Record<string, unknown> {
  const notebookContent = panel.context.model.toJSON() as unknown;
  const directives = parseDirectives(notebookCellSources(notebookContent));
  return buildSnapshotRequestBody({
    source: "manual",
    notebookPath: panel.context.path,
    notebookName: PathExt.basename(panel.context.path),
    documentId: panel.id,
    notebookContent,
    commitMode: options.commitMode,
    runLabel: manualRunLabel(options, dynamicMetadata, directives.runLabel),
    tags: mergeTags(directives.tags, dynamicMetadata.tags, options.tags),
    notes: options.notes,
    extraFields: options.extraFields,
    watchedPaths: readNotebookWatchedPaths(panel),
  });
}

export function buildTriggerBody(
  panel: NotebookPanel,
  lastCell: Cell,
  triggeredCellIds: readonly string[],
  runOutcome: RunOutcome,
  options: SnapshotRequestOptions,
  dynamicMetadata: DynamicKernelMetadata = EMPTY_DYNAMIC_METADATA,
): Record<string, unknown> {
  const notebookContent = panel.context.model.toJSON() as unknown;
  const directives = parseDirectives(notebookCellSources(notebookContent));
  return buildSnapshotRequestBody({
    source: "trigger_cell",
    notebookPath: panel.context.path,
    notebookName: PathExt.basename(panel.context.path),
    documentId: panel.id,
    triggeringCellId: lastCell.model.id,
    triggeredCellIds,
    notebookContent,
    commitMode: options.commitMode,
    runLabel:
      dynamicMetadata.runLabel ??
      directives.runLabel ??
      firstNonBlankSourceLine(lastCell),
    runOutcome,
    tags: mergeTags(directives.tags, dynamicMetadata.tags, options.tags),
    notes: options.notes,
    extraFields: options.extraFields,
    watchedPaths: readNotebookWatchedPaths(panel),
  });
}

export async function collectPanelDynamicMetadata(
  panel: NotebookPanel,
): Promise<DynamicKernelMetadata> {
  return collectDynamicKernelMetadata(
    panel.context.sessionContext.session?.kernel ?? null,
  );
}

export function manualRunLabel(
  options: SnapshotRequestOptions,
  dynamicMetadata: DynamicKernelMetadata,
  directiveRunLabel: string | null,
): string | null {
  if (options.runLabelEdited && options.runLabel !== null) {
    return options.runLabel;
  }
  return dynamicMetadata.runLabel ?? options.runLabel ?? directiveRunLabel;
}
