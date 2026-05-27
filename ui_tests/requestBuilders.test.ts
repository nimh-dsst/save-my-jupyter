import assert from "node:assert/strict";
import test from "node:test";

import type { NotebookPanel } from "@jupyterlab/notebook";

import {
  buildManualSnapshotPayload,
  buildTriggerCellSnapshotPayload,
} from "../src/notebook/requestBuilders";
import type {
  NotebookExtensionMetadata,
  SnapshotUserMetadata,
} from "../src/types";

function createPanel(): NotebookPanel {
  return {
    context: {
      path: "analysis/notebook.ipynb",
    },
    id: "panel-1",
    sessionContext: {
      session: {
        kernel: {
          id: "kernel-1",
        },
      },
    },
    title: {
      label: "Notebook Title",
    },
  } as unknown as NotebookPanel;
}

const notebookMetadata: NotebookExtensionMetadata = {
  all_cells_trigger: false,
  default_metadata: {},
  enabled: true,
  labarchives_target_notebook: null,
  labarchives_target_root_path: null,
  trigger_cell_ids: ["cell-a", "cell-b"],
  watched_paths: ["outputs"],
};

const userMetadata: SnapshotUserMetadata = {
  experiment_context: null,
  extra_fields: { owner: "alice" },
  notes: "run notes",
  run_label: "baseline",
  tags: ["baseline"],
};

void test("buildManualSnapshotPayload creates a manual request", () => {
  const payload = buildManualSnapshotPayload(
    createPanel(),
    notebookMetadata,
    "prompt",
    userMetadata,
  );

  assert.equal(payload.source, "manual");
  assert.equal(payload.notebook_context.document_id, "panel-1");
  assert.equal(payload.notebook_context.notebook_name, "Notebook Title");
  assert.equal(payload.notebook_context.triggering_cell_id, null);
});

void test("buildTriggerCellSnapshotPayload creates a trigger request", () => {
  const payload = buildTriggerCellSnapshotPayload(
    createPanel(),
    notebookMetadata,
    "always",
    userMetadata,
    "cell-a",
  );

  assert.equal(payload.source, "trigger_cell");
  assert.equal(payload.commit_mode, "always");
  assert.equal(payload.notebook_context.kernel_id, "kernel-1");
  assert.equal(payload.notebook_context.triggering_cell_id, "cell-a");
  assert.equal(payload.notebook_context.cell_execution_count, null);
});

void test("buildTriggerCellSnapshotPayload passes through execution count", () => {
  const payload = buildTriggerCellSnapshotPayload(
    createPanel(),
    notebookMetadata,
    "always",
    userMetadata,
    "cell-a",
    7,
  );

  assert.equal(payload.notebook_context.cell_execution_count, 7);
});
