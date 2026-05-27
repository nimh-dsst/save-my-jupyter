import type { Cell } from "@jupyterlab/cells";
import { NotebookActions, type Notebook } from "@jupyterlab/notebook";
import type { IDisposable } from "@lumino/disposable";

import { TriggerCoalescer } from "./triggerCoalescer";

export interface TriggerRun {
  readonly notebook: Notebook;
  readonly lastCell: Cell;
  readonly triggeredCellIds: readonly string[];
}

/** Submits one trigger snapshot per run by accumulating triggered cells on
 * NotebookActions.executed and flushing once on selectionExecuted -- the
 * execution-lifecycle coalescing of contract C-SNAP-08 (no wall-clock timer).
 * Browser-only: exercised through a running JupyterLab. */
export class ExecutionObserver implements IDisposable {
  private readonly coalescer = new TriggerCoalescer<Notebook>();
  private disposed = false;

  constructor(
    private readonly isTriggerCell: (cell: Cell) => boolean,
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

  // Bound arrow properties so they connect/disconnect as stable slots.
  private readonly handleExecuted = (
    _sender: unknown,
    args: { notebook: Notebook; cell: Cell },
  ): void => {
    // Filter on trigger membership only -- never on success -- so an errored
    // run still snapshots (C-SNAP-07).
    if (this.isTriggerCell(args.cell)) {
      this.coalescer.accumulate(args.notebook, args.cell.model.id);
    }
  };

  private readonly handleSelectionExecuted = (
    _sender: unknown,
    args: { notebook: Notebook; lastCell: Cell },
  ): void => {
    if (!this.coalescer.hasPending(args.notebook)) {
      return;
    }
    this.onRun({
      notebook: args.notebook,
      lastCell: args.lastCell,
      triggeredCellIds: this.coalescer.flush(args.notebook),
    });
  };
}
