// Pure trigger-metadata helpers shared by toolbar / commands / context-menu
// wiring. Cell marks live under cell.metadata.save_my_jupyter.trigger and
// notebook-level state under notebook.metadata.save_my_jupyter.all_cells_trigger
// (contracts C-CONFIG-06, C-SNAP-09); the labels and messages match C-CMD-02/03.
// Kept free of JupyterLab types so it is unit-tested without a browser.

export type TriggerCellState = "marked" | "unmarked" | "unknown";

export const COMMAND_SNAPSHOT = "save-my-jupyter:snapshot";
export const COMMAND_OPEN_PANEL = "save-my-jupyter:open-panel";
export const COMMAND_TOGGLE_CELL_TRIGGER =
  "save-my-jupyter:toggle-cell-trigger";
export const COMMAND_MARK_CELL_TRIGGER = "save-my-jupyter:mark-cell-trigger";
export const COMMAND_UNMARK_CELL_TRIGGER =
  "save-my-jupyter:unmark-cell-trigger";
export const COMMAND_TOGGLE_ALL_CELLS_TRIGGER =
  "save-my-jupyter:toggle-all-cells-trigger";

export const ACTIVE_CELL_TRIGGER_CLASS = "smj-Cell--trigger";
export const TRIGGER_CONTEXT_SELECTOR = ".jp-Notebook .jp-Cell";

export const triggerCommandLabels = {
  markCell: "Mark Cell As Trigger",
  openPanel: "Open Snapshot Settings",
  snapshot: "Snapshot Now",
  toggleAllCells: "Toggle All Cells As Triggers",
  toggleCell: "Toggle Cell Trigger",
  unmarkCell: "Unmark Cell As Trigger",
} as const;

export const NO_CELL_SELECTED_WARNING =
  "Select a cell before changing trigger status.";

/** True only when a cell's save_my_jupyter metadata explicitly marks it. */
export function isTriggerMetadata(metadata: unknown): boolean {
  return (
    typeof metadata === "object" &&
    metadata !== null &&
    (metadata as { trigger?: unknown }).trigger === true
  );
}

export function isAllCellsTriggerMetadata(metadata: unknown): boolean {
  return (
    typeof metadata === "object" &&
    metadata !== null &&
    (metadata as { all_cells_trigger?: unknown }).all_cells_trigger === true
  );
}

export function triggerCellState(metadata: unknown): TriggerCellState {
  return isTriggerMetadata(metadata) ? "marked" : "unmarked";
}

function asRecord(metadata: unknown): Record<string, unknown> {
  return typeof metadata === "object" && metadata !== null
    ? { ...(metadata as Record<string, unknown>) }
    : {};
}

/** New cell save_my_jupyter metadata with `trigger` set, other keys preserved. */
export function withTrigger(
  metadata: unknown,
  trigger: boolean,
): Record<string, unknown> {
  return { ...asRecord(metadata), trigger };
}

/** New notebook save_my_jupyter metadata with `all_cells_trigger` set. */
export function withAllCellsTrigger(
  metadata: unknown,
  enabled: boolean,
): Record<string, unknown> {
  return { ...asRecord(metadata), all_cells_trigger: enabled };
}

/** The denormalized trigger_cell_ids view of which cells are marked (C-CONFIG-06). */
export function triggerCellIds(
  cells: readonly { readonly id: string; readonly trigger: boolean }[],
): string[] {
  return cells.filter((cell) => cell.trigger).map((cell) => cell.id);
}

export function withSyncedTriggerCellIds(
  metadata: unknown,
  cells: readonly { readonly id: string; readonly trigger: boolean }[],
): Record<string, unknown> {
  return { ...asRecord(metadata), trigger_cell_ids: triggerCellIds(cells) };
}

export function triggerCellIndexForTarget(
  cells: readonly {
    readonly node: { contains(target: unknown): boolean };
  }[],
  target: unknown,
): number | null {
  const index = cells.findIndex(
    (cell) => cell.node === target || cell.node.contains(target),
  );
  return index >= 0 ? index : null;
}

export function shouldTriggerOnExecution(
  notebookMetadata: unknown,
  cellMetadata: unknown,
): boolean {
  return (
    isAllCellsTriggerMetadata(notebookMetadata) ||
    isTriggerMetadata(cellMetadata)
  );
}

export function shouldDecorateTriggerCell(
  notebookMetadata: unknown,
  cellMetadata: unknown,
): boolean {
  return shouldTriggerOnExecution(notebookMetadata, cellMetadata);
}

/** The adaptive context-menu / command label for the trigger toggle (C-CMD-02). */
export function triggerToggleLabel(state: TriggerCellState): string {
  switch (state) {
    case "marked":
      return "Unmark Cell As Trigger";
    case "unmarked":
      return "Mark Cell As Trigger";
    case "unknown":
      return "Toggle Cell Trigger";
  }
}

export function triggerModeDescription(allCellsTrigger: boolean): string {
  return allCellsTrigger ? "Every executed cell" : "Marked trigger cells only";
}

export function activeCellTriggerDescription(state: TriggerCellState): string {
  switch (state) {
    case "marked":
      return "Marked as trigger";
    case "unmarked":
      return "Not marked as trigger";
    case "unknown":
      return "No active cell";
  }
}

/** The confirming status shown when all-cells-trigger mode changes (C-CMD-03). */
export function allCellsConfirmMessage(enabled: boolean): string {
  return enabled
    ? "Every executed cell will trigger snapshots."
    : "Only marked trigger cells will create automatic snapshots.";
}
