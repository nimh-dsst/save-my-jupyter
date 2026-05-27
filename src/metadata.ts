import type { Cell } from "@jupyterlab/cells";
import type { NotebookPanel } from "@jupyterlab/notebook";

import {
  type CellExtensionMetadata,
  type NotebookExtensionMetadata,
  parseCellExtensionMetadata,
  parseNotebookExtensionMetadata,
} from "./types";

export const NOTEBOOK_METADATA_KEY = "save_my_jupyter";
export const CELL_METADATA_KEY = "save_my_jupyter";

export interface ActiveCellTriggerState {
  cellId: string | null;
  isTrigger: boolean;
}

export class NotebookMetadataStore {
  readNotebookMetadata(panel: NotebookPanel): NotebookExtensionMetadata {
    const model = panel.content.model;
    const raw = model?.sharedModel.getMetadata(NOTEBOOK_METADATA_KEY);
    return parseNotebookExtensionMetadata(raw ?? {});
  }

  async writeNotebookMetadata(
    panel: NotebookPanel,
    metadata: NotebookExtensionMetadata,
  ): Promise<void> {
    const model = panel.content.model;
    model?.sharedModel.setMetadata(NOTEBOOK_METADATA_KEY, metadata);
    await panel.context.save();
  }

  readCellMetadata(cell: Cell): CellExtensionMetadata {
    const raw = cell.model.sharedModel.getMetadata(CELL_METADATA_KEY);
    return parseCellExtensionMetadata(raw ?? {});
  }

  readActiveCellTriggerState(panel: NotebookPanel): ActiveCellTriggerState {
    const activeCell = panel.content.activeCell;
    if (activeCell === null) {
      return {
        cellId: null,
        isTrigger: false,
      };
    }

    return {
      cellId: activeCell.model.id,
      isTrigger: this.readCellMetadata(activeCell).trigger,
    };
  }

  setCellTrigger(cell: Cell, enabled: boolean): void {
    const metadata = this.readCellMetadata(cell);
    cell.model.sharedModel.setMetadata(CELL_METADATA_KEY, {
      ...metadata,
      trigger: enabled,
    });
  }

  async setCellTriggerForPanel(
    panel: NotebookPanel,
    cell: Cell,
    enabled: boolean,
  ): Promise<NotebookExtensionMetadata> {
    this.setCellTrigger(cell, enabled);

    const metadata = this.readNotebookMetadata(panel);
    const triggerCellIds = new Set(metadata.trigger_cell_ids);
    if (enabled) {
      triggerCellIds.add(cell.model.id);
    } else {
      triggerCellIds.delete(cell.model.id);
    }

    const nextMetadata: NotebookExtensionMetadata = {
      ...metadata,
      trigger_cell_ids: [...triggerCellIds],
    };
    await this.writeNotebookMetadata(panel, nextMetadata);
    return nextMetadata;
  }
}
