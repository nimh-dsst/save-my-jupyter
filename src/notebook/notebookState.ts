import type { Cell } from "@jupyterlab/cells";
import type { Notebook, NotebookPanel } from "@jupyterlab/notebook";

import { joinSource } from "./sourceText";
import {
  ACTIVE_CELL_TRIGGER_CLASS,
  NO_CELL_SELECTED_WARNING,
  allCellsConfirmMessage,
  isAllCellsTriggerMetadata,
  isTriggerMetadata,
  shouldDecorateTriggerCell,
  shouldTriggerOnExecution,
  triggerCellIndexForTarget,
  triggerCellState,
  withAllCellsTrigger,
  withSyncedTriggerCellIds,
  withTrigger,
  type TriggerCellState,
} from "./triggers";
import {
  readWatchedPaths,
  type WatchedPathAddResult,
  withAddedWatchedPath,
  withoutWatchedPath,
} from "./watchedPaths";

export interface TriggerOptions {
  readonly activeCell: TriggerCellState;
  readonly allCellsTrigger: boolean;
}

export interface TargetOptions {
  readonly notebookName: string;
  readonly rootPath: string;
}

export type TargetOptionsPatch = Partial<TargetOptions>;

export const EXTENSION_METADATA_KEY = "save_my_jupyter";
const OPEN_NOTEBOOK_WATCHED_FILES_MESSAGE =
  "Open a notebook before adding tracked files.";

export function shouldSnapshotCell(notebook: Notebook, cell: Cell): boolean {
  return shouldTriggerOnExecution(
    notebook.model?.getMetadata(EXTENSION_METADATA_KEY),
    readCellMetadata(cell),
  );
}

export function isFinalNotebookCell(notebook: Notebook, cell: Cell): boolean {
  const cellIndex = notebook.widgets.indexOf(cell);
  if (cellIndex < 0) {
    return false;
  }
  return notebook.widgets.slice(cellIndex + 1).every(isBlankTailCell);
}

export function readTriggerOptions(
  panel: NotebookPanel | null,
): TriggerOptions {
  if (panel === null) {
    return { activeCell: "unknown", allCellsTrigger: false };
  }
  return {
    activeCell: readActiveCellTriggerState(panel),
    allCellsTrigger: isAllCellsTriggerMetadata(readNotebookMetadata(panel)),
  };
}

export function readNotebookWatchedPaths(
  panel: NotebookPanel | null,
): string[] {
  if (panel === null) {
    return [];
  }
  return readWatchedPaths(readNotebookMetadata(panel));
}

export function readTargetOptions(panel: NotebookPanel | null): TargetOptions {
  if (panel === null) {
    return { notebookName: "", rootPath: "" };
  }
  const metadata = asRecord(readNotebookMetadata(panel));
  return {
    notebookName: asString(metadata["labarchives_target_notebook"]),
    rootPath: asString(metadata["labarchives_target_root_path"]),
  };
}

export function addWatchedPath(
  panel: NotebookPanel | null,
  path: string,
  refreshUi: () => void,
): WatchedPathAddResult {
  if (panel === null) {
    return {
      ok: false,
      message: OPEN_NOTEBOOK_WATCHED_FILES_MESSAGE,
    };
  }
  const currentMetadata = readNotebookMetadata(panel);
  const result = withAddedWatchedPath(currentMetadata, path);
  if (!result.ok) {
    return result;
  }
  writeNotebookMetadata(panel, result.metadata);
  refreshUi();
  return result;
}

export function removeWatchedPath(
  panel: NotebookPanel | null,
  path: string,
): void {
  if (panel === null) {
    return;
  }
  const currentMetadata = readNotebookMetadata(panel);
  const next = withoutWatchedPath(currentMetadata, path);
  if (metadataEqual(currentMetadata, next.metadata)) {
    return;
  }
  writeNotebookMetadata(panel, next.metadata);
}

export function updateTargetOptions(
  panel: NotebookPanel | null,
  patch: TargetOptionsPatch,
): void {
  if (panel === null) {
    return;
  }
  const currentMetadata = readNotebookMetadata(panel);
  const next = { ...asRecord(currentMetadata) };
  setOptionalString(next, "labarchives_target_notebook", patch.notebookName);
  setOptionalString(next, "labarchives_target_root_path", patch.rootPath);
  if (metadataEqual(currentMetadata, next)) {
    return;
  }
  writeNotebookMetadata(panel, next);
}

export function toggleActiveCellTrigger(
  panel: NotebookPanel | null,
  notifyWarning: (message: string) => void,
): void {
  const activeState =
    panel !== null ? readActiveCellTriggerState(panel) : "unknown";
  setActiveCellTrigger(panel, activeState !== "marked", notifyWarning);
}

export function setActiveCellTrigger(
  panel: NotebookPanel | null,
  trigger: boolean,
  notifyWarning: (message: string) => void,
): void {
  const cell = panel?.content.activeCell ?? null;
  if (panel === null || cell === null) {
    notifyWarning(NO_CELL_SELECTED_WARNING);
    return;
  }
  writeCellMetadata(cell, withTrigger(readCellMetadata(cell), trigger));
  syncTriggerCellDecoration(cell, readNotebookMetadata(panel));
  syncNotebookTriggerCellIds(panel);
}

export function toggleAllCellsTrigger(
  panel: NotebookPanel | null,
  notifyInfo: (message: string) => void,
  notifyWarning: (message: string) => void,
): void {
  if (panel === null) {
    notifyWarning(NO_CELL_SELECTED_WARNING);
    return;
  }
  const metadata = readNotebookMetadata(panel);
  const enabled = !isAllCellsTriggerMetadata(metadata);
  writeNotebookMetadata(panel, withAllCellsTrigger(metadata, enabled));
  syncTriggerCellDecorations(panel);
  notifyInfo(allCellsConfirmMessage(enabled));
}

export function syncNotebookTriggerCellIds(panel: NotebookPanel): void {
  const cells = panel.content.widgets.map((cell) => ({
    id: cell.model.id,
    trigger: isTriggerMetadata(readCellMetadata(cell)),
  }));
  const currentMetadata = readNotebookMetadata(panel);
  const nextMetadata = withSyncedTriggerCellIds(currentMetadata, cells);
  if (metadataEqual(currentMetadata, nextMetadata)) {
    return;
  }
  writeNotebookMetadata(panel, nextMetadata);
}

export function syncTriggerCellDecorations(panel: NotebookPanel): void {
  const notebookMetadata = readNotebookMetadata(panel);
  panel.content.widgets.forEach((cell) => {
    syncTriggerCellDecoration(cell, notebookMetadata);
  });
}

export function setupNotebookPanel(
  panel: NotebookPanel,
  configuredNotebookPanels: WeakSet<NotebookPanel>,
  refreshTriggerUi: () => void,
): void {
  if (configuredNotebookPanels.has(panel)) {
    return;
  }
  configuredNotebookPanels.add(panel);
  syncTriggerCellDecorations(panel);
  const handleContextMenu = (event: MouseEvent): void => {
    const index = triggerCellIndexForTarget(panel.content.widgets, event.target);
    if (index === null) {
      return;
    }
    panel.content.activeCellIndex = index;
    refreshTriggerUi();
  };
  panel.content.node.addEventListener("contextmenu", handleContextMenu, true);
  panel.disposed.connect(() => {
    panel.content.node.removeEventListener(
      "contextmenu",
      handleContextMenu,
      true,
    );
  });
  panel.content.modelContentChanged.connect(() => {
    syncTriggerCellDecorations(panel);
    refreshTriggerUi();
  });
}

export function readNotebookMetadata(panel: NotebookPanel): unknown {
  return panel.context.model.getMetadata(EXTENSION_METADATA_KEY);
}

export function readCellMetadata(cell: Cell): unknown {
  return cell.model.getMetadata(EXTENSION_METADATA_KEY);
}

function readActiveCellTriggerState(panel: NotebookPanel): TriggerCellState {
  const cell = panel.content.activeCell;
  if (cell === null) {
    return "unknown";
  }
  return triggerCellState(readCellMetadata(cell));
}

function writeNotebookMetadata(
  panel: NotebookPanel,
  metadata: Record<string, unknown>,
): void {
  panel.context.model.setMetadata(EXTENSION_METADATA_KEY, metadata);
}

function writeCellMetadata(
  cell: Cell,
  metadata: Record<string, unknown>,
): void {
  cell.model.setMetadata(EXTENSION_METADATA_KEY, metadata);
}

function metadataEqual(left: unknown, right: Record<string, unknown>): boolean {
  if (typeof left !== "object" || left === null) {
    return Object.keys(right).length === 0;
  }
  return JSON.stringify(left) === JSON.stringify(right);
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? { ...(value as Record<string, unknown>) }
    : {};
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function isBlankTailCell(cell: Cell): boolean {
  const cellJson = asRecord(cell.model.toJSON() as unknown);
  return (
    joinSource(cellJson["source"]).trim().length === 0 &&
    !hasOutputs(cellJson["outputs"])
  );
}

function hasOutputs(value: unknown): boolean {
  return Array.isArray(value) && value.length > 0;
}

function setOptionalString(
  target: Record<string, unknown>,
  key: string,
  value: string | undefined,
): void {
  if (value === undefined) {
    return;
  }
  if (value.trim().length === 0) {
    Reflect.deleteProperty(target, key);
    return;
  }
  target[key] = value;
}

function syncTriggerCellDecoration(
  cell: Cell,
  notebookMetadata: unknown,
): void {
  if (shouldDecorateTriggerCell(notebookMetadata, readCellMetadata(cell))) {
    cell.addClass(ACTIVE_CELL_TRIGGER_CLASS);
  } else {
    cell.removeClass(ACTIVE_CELL_TRIGGER_CLASS);
  }
}
