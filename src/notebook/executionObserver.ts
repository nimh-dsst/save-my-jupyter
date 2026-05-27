import type { Cell } from "@jupyterlab/cells";
import { NotebookActions, type Notebook } from "@jupyterlab/notebook";
import type { IDisposable } from "@lumino/disposable";

import type { RunOutcome } from "../types";

import { TriggerCoalescer } from "./triggerCoalescer";

export interface TriggerRun {
  readonly notebook: Notebook;
  readonly lastCell: Cell;
  readonly runOutcome: RunOutcome;
  readonly triggeredCellIds: readonly string[];
}

/** Submits one trigger snapshot per run by accumulating triggered cells on
 * NotebookActions.executed and flushing once on selectionExecuted -- the
 * execution-lifecycle coalescing of contract C-SNAP-08 (no wall-clock timer).
 * Browser-only: exercised through a running JupyterLab. */
export class ExecutionObserver implements IDisposable {
  private readonly coalescer = new TriggerCoalescer<Notebook>();
  private readonly failedRuns = new WeakSet<Notebook>();
  private readonly lastCells = new WeakMap<Notebook, Cell>();
  private disposed = false;

  constructor(
    private readonly shouldSnapshotCell: (
      notebook: Notebook,
      cell: Cell,
    ) => boolean,
    private readonly onRun: (run: TriggerRun) => void,
  ) {}

  start(): void {
    NotebookActions.executed.connect(this.handleExecuted);
    NotebookActions.selectionExecuted.connect(this.handleSelectionExecuted);
  }

  get isDisposed(): boolean {
    return this.disposed;
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    NotebookActions.executed.disconnect(this.handleExecuted);
    NotebookActions.selectionExecuted.disconnect(this.handleSelectionExecuted);
  }

  flushPendingOnIdle(notebook: Notebook): void {
    const lastCell = this.lastCells.get(notebook);
    if (lastCell === undefined || !this.coalescer.hasPending(notebook)) {
      return;
    }
    this.flush(notebook, lastCell);
  }

  // Bound arrow properties so they connect/disconnect as stable slots.
  private readonly handleExecuted = (
    _sender: unknown,
    args: { notebook: Notebook; cell: Cell; success?: boolean },
  ): void => {
    if (args.success === false) {
      this.failedRuns.add(args.notebook);
    }
    this.lastCells.set(args.notebook, args.cell);
    // Filter on trigger membership only -- never on success -- so an errored
    // run still snapshots (C-SNAP-07).
    if (this.shouldSnapshotCell(args.notebook, args.cell)) {
      this.coalescer.accumulate(args.notebook, args.cell.model.id);
    }
  };

  private readonly handleSelectionExecuted = (
    _sender: unknown,
    args: { notebook: Notebook; lastCell: Cell },
  ): void => {
    if (!this.coalescer.hasPending(args.notebook)) {
      this.failedRuns.delete(args.notebook);
      return;
    }
    this.flush(args.notebook, args.lastCell);
  };

  private flush(notebook: Notebook, lastCell: Cell): void {
    const runOutcome = this.failedRuns.has(notebook) ? "error" : "success";
    this.failedRuns.delete(notebook);
    this.lastCells.delete(notebook);
    this.onRun({
      notebook,
      lastCell,
      runOutcome,
      triggeredCellIds: this.coalescer.flush(notebook),
    });
  }
}
