import assert from "node:assert/strict";
import test from "node:test";

import type { Cell } from "@jupyterlab/cells";
import type { INotebookTracker, NotebookPanel } from "@jupyterlab/notebook";

import {
  ExecutionObserver,
  type ExecutionCompletedEvent,
  type ExecutionMetadataStore,
} from "../src/notebook/triggerHooks";
import type {
  CommitMode,
  SnapshotRequestPayload,
  SnapshotUserMetadata,
} from "../src/types";

class FakeSignal {
  private handler:
    | ((sender: unknown, args: ExecutionCompletedEvent) => void)
    | null = null;

  connect(
    slot: (sender: unknown, args: ExecutionCompletedEvent) => void,
  ): void {
    this.handler = slot;
  }

  disconnect(
    slot: (sender: unknown, args: ExecutionCompletedEvent) => void,
  ): void {
    if (this.handler === slot) {
      this.handler = null;
    }
  }

  emit(args: ExecutionCompletedEvent): void {
    this.handler?.(this, args);
  }
}

function createPanel(): NotebookPanel {
  return {
    content: {
      activeCell: null,
    },
    context: {
      path: "analysis/notebook.ipynb",
      save: async () => {
        await Promise.resolve();
      },
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

function createTracker(panel: NotebookPanel): INotebookTracker {
  return {
    find: (predicate: (candidate: NotebookPanel) => boolean) =>
      predicate(panel) ? panel : undefined,
  } as unknown as INotebookTracker;
}

function createCell(cellId: string): Cell {
  return {
    model: {
      id: cellId,
    },
  } as unknown as Cell;
}

const userMetadata: SnapshotUserMetadata = {
  experiment_context: null,
  extra_fields: {},
  notes: null,
  run_label: null,
  tags: [],
};

function requireTriggerPayload(
  payload: SnapshotRequestPayload | undefined,
): Extract<SnapshotRequestPayload, { source: "trigger_cell" }> {
  if (payload?.source !== "trigger_cell") {
    throw new Error("Expected a trigger-cell payload.");
  }
  return payload;
}

void test("ExecutionObserver emits payloads for marked trigger cells", async () => {
  const panel = createPanel();
  const signal = new FakeSignal();
  let resolvePayload: ((payload: SnapshotRequestPayload) => void) | undefined;
  const payloadPromise = new Promise<SnapshotRequestPayload>((resolve) => {
    resolvePayload = resolve;
  });
  const metadataStore = {
    readCellMetadata: () => ({ trigger: true }),
    readNotebookMetadata: () => ({
      all_cells_trigger: false,
      default_metadata: {},
      enabled: true,
      labarchives_target_notebook: null,
      labarchives_target_root_path: null,
      trigger_cell_ids: [],
      watched_paths: [],
    }),
  } satisfies ExecutionMetadataStore;

  const observer = new ExecutionObserver(
    createTracker(panel),
    metadataStore,
    (payload) => {
      resolvePayload?.(payload);
      return Promise.resolve();
    },
    (): CommitMode => "prompt",
    (): SnapshotUserMetadata => userMetadata,
    signal,
  );
  const disposable = observer.attach();

  signal.emit({
    cell: createCell("cell-1"),
    notebook: panel.content,
    success: true,
  });
  const receivedPayload = await payloadPromise;

  assert.equal(receivedPayload.source, "trigger_cell");
  assert.equal(receivedPayload.notebook_context.triggering_cell_id, "cell-1");

  disposable.dispose();
});

void test("ExecutionObserver coalesces rapid trigger events into one snapshot", async () => {
  const panel = createPanel();
  const signal = new FakeSignal();
  const payloads: SnapshotRequestPayload[] = [];
  const metadataStore = {
    readCellMetadata: () => ({ trigger: true }),
    readNotebookMetadata: () => ({
      all_cells_trigger: false,
      default_metadata: {},
      enabled: true,
      labarchives_target_notebook: null,
      labarchives_target_root_path: null,
      trigger_cell_ids: [],
      watched_paths: [],
    }),
  } satisfies ExecutionMetadataStore;

  const observer = new ExecutionObserver(
    createTracker(panel),
    metadataStore,
    (payload) => {
      payloads.push(payload);
      return Promise.resolve();
    },
    (): CommitMode => "prompt",
    (): SnapshotUserMetadata => userMetadata,
    signal,
    { coalesceMs: 5 },
  );
  const disposable = observer.attach();

  signal.emit({
    cell: createCell("cell-1"),
    notebook: panel.content,
    success: true,
  });
  signal.emit({
    cell: createCell("cell-2"),
    notebook: panel.content,
    success: true,
  });
  signal.emit({
    cell: createCell("cell-3"),
    notebook: panel.content,
    success: true,
  });

  await new Promise((resolve) => setTimeout(resolve, 40));

  assert.equal(payloads.length, 1);
  const coalesced = requireTriggerPayload(payloads[0]);
  assert.equal(coalesced.source, "trigger_cell");
  assert.equal(coalesced.notebook_context.triggering_cell_id, "cell-3");
  assert.deepEqual([...coalesced.notebook_context.cell_ids].sort(), [
    "cell-1",
    "cell-2",
    "cell-3",
  ]);

  disposable.dispose();
});

void test("ExecutionObserver emits separate snapshots after the coalesce window closes", async () => {
  const panel = createPanel();
  const signal = new FakeSignal();
  const payloads: SnapshotRequestPayload[] = [];
  const metadataStore = {
    readCellMetadata: () => ({ trigger: true }),
    readNotebookMetadata: () => ({
      all_cells_trigger: false,
      default_metadata: {},
      enabled: true,
      labarchives_target_notebook: null,
      labarchives_target_root_path: null,
      trigger_cell_ids: [],
      watched_paths: [],
    }),
  } satisfies ExecutionMetadataStore;

  const observer = new ExecutionObserver(
    createTracker(panel),
    metadataStore,
    (payload) => {
      payloads.push(payload);
      return Promise.resolve();
    },
    (): CommitMode => "prompt",
    (): SnapshotUserMetadata => userMetadata,
    signal,
    { coalesceMs: 5 },
  );
  const disposable = observer.attach();

  signal.emit({
    cell: createCell("cell-a"),
    notebook: panel.content,
    success: true,
  });
  await new Promise((resolve) => setTimeout(resolve, 30));
  signal.emit({
    cell: createCell("cell-b"),
    notebook: panel.content,
    success: true,
  });
  await new Promise((resolve) => setTimeout(resolve, 30));

  assert.equal(payloads.length, 2);
  const first = requireTriggerPayload(payloads[0]);
  const second = requireTriggerPayload(payloads[1]);
  assert.equal(first.notebook_context.triggering_cell_id, "cell-a");
  assert.equal(second.notebook_context.triggering_cell_id, "cell-b");

  disposable.dispose();
});

void test("ExecutionObserver ignores non-trigger cells", async () => {
  const panel = createPanel();
  const signal = new FakeSignal();
  let callCount = 0;
  const metadataStore = {
    readCellMetadata: () => ({ trigger: false }),
    readNotebookMetadata: () => ({
      all_cells_trigger: false,
      default_metadata: {},
      enabled: true,
      labarchives_target_notebook: null,
      labarchives_target_root_path: null,
      trigger_cell_ids: [],
      watched_paths: [],
    }),
  } satisfies ExecutionMetadataStore;

  const observer = new ExecutionObserver(
    createTracker(panel),
    metadataStore,
    () => {
      callCount += 1;
      return Promise.resolve();
    },
    (): CommitMode => "prompt",
    (): SnapshotUserMetadata => userMetadata,
    signal,
  );
  const disposable = observer.attach();

  signal.emit({
    cell: createCell("cell-2"),
    notebook: panel.content,
    success: true,
  });
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(callCount, 0);

  disposable.dispose();
});
