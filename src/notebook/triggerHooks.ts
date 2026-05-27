import type { Cell } from "@jupyterlab/cells";
import {
  type INotebookTracker,
  type NotebookPanel,
} from "@jupyterlab/notebook";
import type { IDisposable } from "@lumino/disposable";

import type {
  CellExtensionMetadata,
  CommitMode,
  NotebookExtensionMetadata,
  SnapshotRequestPayload,
  SnapshotUserMetadata,
} from "../types";

import { buildTriggerCellSnapshotPayload } from "./requestBuilders";

const DEFAULT_COALESCE_MS = 500;

class SimpleDisposable implements IDisposable {
  readonly isDisposed = false;

  constructor(private readonly cleanup: () => void) {}

  dispose(): void {
    this.cleanup();
  }
}

export interface ExecutionCompletedEvent {
  cell: Cell;
  notebook: NotebookPanel["content"];
  success: boolean;
}

export interface ExecutionCompletedSignal {
  connect(slot: (sender: unknown, args: ExecutionCompletedEvent) => void): void;
  disconnect(
    slot: (sender: unknown, args: ExecutionCompletedEvent) => void,
  ): void;
}

export interface ExecutionMetadataStore {
  readCellMetadata(cell: Cell): CellExtensionMetadata;
  readNotebookMetadata(panel: NotebookPanel): NotebookExtensionMetadata;
}

export interface ExecutionObserverOptions {
  coalesceMs?: number;
}

interface PendingTrigger {
  payload: SnapshotRequestPayload;
  triggeredCellIds: Set<string>;
  timer: ReturnType<typeof setTimeout>;
}

export class ExecutionObserver {
  private readonly coalesceMs: number;
  private readonly pendingByNotebook = new Map<string, PendingTrigger>();

  constructor(
    private readonly tracker: INotebookTracker,
    private readonly metadataStore: ExecutionMetadataStore,
    private readonly onTrigger: (
      payload: SnapshotRequestPayload,
    ) => Promise<void>,
    private readonly commitModeProvider: () => CommitMode,
    private readonly userMetadataProvider: () => SnapshotUserMetadata,
    private readonly executionEvents: ExecutionCompletedSignal,
    options: ExecutionObserverOptions = {},
  ) {
    this.coalesceMs = options.coalesceMs ?? DEFAULT_COALESCE_MS;
  }

  attach(): IDisposable {
    const onExecuted = (
      sender: unknown,
      event: ExecutionCompletedEvent,
    ): void => {
      void sender;
      void this.handleExecuted(event);
    };

    this.executionEvents.connect(onExecuted);
    return new SimpleDisposable(() => {
      this.executionEvents.disconnect(onExecuted);
    });
  }

  private async handleExecuted(event: ExecutionCompletedEvent): Promise<void> {
    if (!event.success) {
      return;
    }

    const panel = this.tracker.find(
      (candidate) => candidate.content === event.notebook,
    );
    if (panel === undefined) {
      return;
    }

    const notebookMetadata = this.metadataStore.readNotebookMetadata(panel);
    const cellMetadata = this.metadataStore.readCellMetadata(event.cell);
    if (!notebookMetadata.all_cells_trigger && !cellMetadata.trigger) {
      return;
    }

    const triggeringCellId = event.cell.model.id;
    const cellExecutionCount = readCellExecutionCount(event.cell);

    await panel.context.save();

    const payload = buildTriggerCellSnapshotPayload(
      panel,
      notebookMetadata,
      this.commitModeProvider(),
      this.userMetadataProvider(),
      triggeringCellId,
      cellExecutionCount,
    );

    const notebookKey = panel.context.path;
    const existing = this.pendingByNotebook.get(notebookKey);
    if (existing !== undefined) {
      clearTimeout(existing.timer);
      existing.triggeredCellIds.add(triggeringCellId);
    }
    const triggeredCellIds =
      existing?.triggeredCellIds ?? new Set([triggeringCellId]);
    const timer = setTimeout(() => {
      void this.flush(notebookKey);
    }, this.coalesceMs);
    this.pendingByNotebook.set(notebookKey, {
      payload,
      timer,
      triggeredCellIds,
    });
  }

  private async flush(notebookKey: string): Promise<void> {
    const pending = this.pendingByNotebook.get(notebookKey);
    if (pending === undefined) {
      return;
    }
    this.pendingByNotebook.delete(notebookKey);

    const payload: SnapshotRequestPayload = {
      ...pending.payload,
      notebook_context: {
        ...pending.payload.notebook_context,
        cell_ids: [...pending.triggeredCellIds],
      },
    };
    await this.onTrigger(payload);
  }
}

function readCellExecutionCount(cell: Cell): number | null {
  const model = cell.model as { executionCount?: number | null };
  const value = model.executionCount;
  return typeof value === "number" ? value : null;
}
