import assert from "node:assert/strict";
import test from "node:test";

import type { Cell } from "@jupyterlab/cells";
import type { NotebookPanel } from "@jupyterlab/notebook";

import { NotebookMetadataStore, NOTEBOOK_METADATA_KEY } from "../src/metadata";

type MetadataValue = Record<string, unknown>;

class FakeSharedModel {
  private metadata = new Map<string, MetadataValue>();

  getMetadata(key: string): MetadataValue | undefined {
    return this.metadata.get(key);
  }

  setMetadata(key: string, value: MetadataValue): void {
    this.metadata.set(key, value);
  }
}

function createPanel(sharedModel: FakeSharedModel): NotebookPanel {
  let saveCount = 0;

  return {
    content: {
      model: {
        sharedModel
      }
    },
    context: {
      save: async () => {
        await Promise.resolve();
        saveCount += 1;
      }
    },
    get saveCount(): number {
      return saveCount;
    }
  } as unknown as NotebookPanel;
}

function createCell(sharedModel: FakeSharedModel, id: string): Cell {
  return {
    model: {
      id,
      sharedModel
    }
  } as unknown as Cell;
}

void test("NotebookMetadataStore writes defaults and syncs trigger ids", async () => {
  const notebookSharedModel = new FakeSharedModel();
  const cellSharedModel = new FakeSharedModel();
  const panel = createPanel(notebookSharedModel);
  const cell = createCell(cellSharedModel, "cell-1");
  const store = new NotebookMetadataStore();

  await store.writeNotebookMetadata(panel, {
    all_cells_trigger: false,
    default_metadata: {},
    enabled: true,
    labarchives_target_notebook: null,
    labarchives_target_root_path: null,
    trigger_cell_ids: [],
    watched_paths: []
  });

  const nextMetadata = await store.setCellTriggerForPanel(panel, cell, true);

  assert.equal(store.readCellMetadata(cell).trigger, true);
  assert.deepEqual(nextMetadata.trigger_cell_ids, ["cell-1"]);
  assert.deepEqual(
    notebookSharedModel.getMetadata(NOTEBOOK_METADATA_KEY),
    nextMetadata
  );
});

void test("NotebookMetadataStore removes trigger ids when cells are unmarked", async () => {
  const notebookSharedModel = new FakeSharedModel();
  const cellSharedModel = new FakeSharedModel();
  const panel = createPanel(notebookSharedModel);
  const cell = createCell(cellSharedModel, "cell-2");
  const store = new NotebookMetadataStore();

  await store.writeNotebookMetadata(panel, {
    all_cells_trigger: false,
    default_metadata: {},
    enabled: true,
    labarchives_target_notebook: null,
    labarchives_target_root_path: null,
    trigger_cell_ids: ["cell-2"],
    watched_paths: []
  });

  const nextMetadata = await store.setCellTriggerForPanel(panel, cell, false);

  assert.equal(store.readCellMetadata(cell).trigger, false);
  assert.deepEqual(nextMetadata.trigger_cell_ids, []);
});
