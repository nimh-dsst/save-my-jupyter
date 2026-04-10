import type { Cell } from "@jupyterlab/cells";
import {
  type INotebookTracker,
  type NotebookPanel
} from "@jupyterlab/notebook";
import type { IDisposable } from "@lumino/disposable";

import type {
  CellExtensionMetadata,
  CommitMode,
  NotebookExtensionMetadata,
  SnapshotUserMetadata
} from "../types";

import { buildTriggerCellSnapshotPayload } from "./requestBuilders";

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
  disconnect(slot: (sender: unknown, args: ExecutionCompletedEvent) => void): void;
}

export interface ExecutionMetadataStore {
  readCellMetadata(cell: Cell): CellExtensionMetadata;
  readNotebookMetadata(panel: NotebookPanel): NotebookExtensionMetadata;
}

export class ExecutionObserver {
  constructor(
    private readonly tracker: INotebookTracker,
    private readonly metadataStore: ExecutionMetadataStore,
    private readonly onTrigger: (payload: ReturnType<typeof buildTriggerCellSnapshotPayload>) => Promise<void>,
    private readonly commitModeProvider: () => CommitMode,
    private readonly userMetadataProvider: () => SnapshotUserMetadata,
    private readonly executionEvents: ExecutionCompletedSignal
  ) {}

  attach(): IDisposable {
    const onExecuted = (
      sender: unknown,
      event: ExecutionCompletedEvent
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

    const panel = this.tracker.find(candidate => candidate.content === event.notebook);
    if (panel === undefined) {
      return;
    }

    const notebookMetadata = this.metadataStore.readNotebookMetadata(panel);
    const cellMetadata = this.metadataStore.readCellMetadata(event.cell);
    if (!notebookMetadata.all_cells_trigger && !cellMetadata.trigger) {
      return;
    }

    const triggeringCellId = event.cell.model.id;

    await panel.context.save();

    const payload = buildTriggerCellSnapshotPayload(
      panel,
      notebookMetadata,
      this.commitModeProvider(),
      this.userMetadataProvider(),
      triggeringCellId
    );
    await this.onTrigger(payload);
  }
}
