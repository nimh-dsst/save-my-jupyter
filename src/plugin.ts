import type {
  JupyterFrontEnd,
  JupyterFrontEndPlugin,
} from "@jupyterlab/application";
import { ICommandPalette } from "@jupyterlab/apputils";
import type { Cell } from "@jupyterlab/cells";
import { PathExt } from "@jupyterlab/coreutils";
import {
  INotebookTracker,
  type Notebook,
  type NotebookPanel,
} from "@jupyterlab/notebook";

import { ApiClient } from "./apiClient";
import {
  ExecutionObserver,
  type TriggerRun,
} from "./notebook/executionObserver";
import { buildSnapshotRequestBody } from "./notebook/requestBuilders";
import { SnapshotPanelController } from "./panel/controller";
import { SnapshotPanel } from "./panel/SnapshotPanel";

const PLUGIN_ID = "@save-my-jupyter/extension:plugin";
const COMMAND_SNAPSHOT = "save-my-jupyter:snapshot";

const plugin: JupyterFrontEndPlugin<void> = {
  id: PLUGIN_ID,
  autoStart: true,
  requires: [INotebookTracker],
  optional: [ICommandPalette],
  activate: (
    app: JupyterFrontEnd,
    notebooks: INotebookTracker,
    palette: ICommandPalette | null,
  ): void => {
    const controller = new SnapshotPanelController(new ApiClient());

    const snapshotCurrent = async (): Promise<void> => {
      const current = notebooks.currentWidget;
      if (current !== null) {
        await controller.snapshot(buildManualBody(current));
      }
    };

    const connect = async (): Promise<void> => {
      // Opening the LabArchives sign-in flow is the gate-unverifiable seam,
      // wired during the smoke test; refresh status to reflect any change.
      await controller.refreshAuth();
    };

    const panel = new SnapshotPanel({
      state: controller.state,
      onConnect: () => {
        void connect();
      },
      onSnapshot: () => {
        void snapshotCurrent();
      },
    });
    app.shell.add(panel, "right", { rank: 1000 });

    void controller.refreshAuth();
    void controller.refreshActivity();
    notebooks.currentChanged.connect((_tracker, current) => {
      controller.setNotebookName(current !== null ? current.context.path : null);
    });

    app.commands.addCommand(COMMAND_SNAPSHOT, {
      label: "Snapshot Now",
      execute: () => {
        void snapshotCurrent();
      },
    });
    if (palette !== null) {
      palette.addItem({ command: COMMAND_SNAPSHOT, category: "Save My Jupyter" });
    }

    const submitTrigger = async (run: TriggerRun): Promise<void> => {
      const current = findPanel(notebooks, run.notebook);
      if (current !== null) {
        await controller.snapshot(
          buildTriggerBody(current, run.lastCell, run.triggeredCellIds),
        );
      }
    };
    const observer = new ExecutionObserver(isTriggerCell, (run) => {
      void submitTrigger(run);
    });
    observer.start();
    app.shell.disposed.connect(() => {
      observer.dispose();
    });
  },
};

function buildManualBody(panel: NotebookPanel): Record<string, unknown> {
  return buildSnapshotRequestBody({
    source: "manual",
    notebookPath: panel.context.path,
    notebookName: PathExt.basename(panel.context.path),
    documentId: panel.id,
    notebookContent: panel.context.model.toJSON() as unknown,
  });
}

function buildTriggerBody(
  panel: NotebookPanel,
  lastCell: Cell,
  triggeredCellIds: readonly string[],
): Record<string, unknown> {
  return buildSnapshotRequestBody({
    source: "trigger_cell",
    notebookPath: panel.context.path,
    notebookName: PathExt.basename(panel.context.path),
    documentId: panel.id,
    triggeringCellId: lastCell.model.id,
    triggeredCellIds,
    notebookContent: panel.context.model.toJSON() as unknown,
  });
}

function isTriggerCell(cell: Cell): boolean {
  const metadata: unknown = cell.model.getMetadata("save_my_jupyter");
  return (
    typeof metadata === "object" &&
    metadata !== null &&
    (metadata as { trigger?: unknown }).trigger === true
  );
}

function findPanel(
  notebooks: INotebookTracker,
  notebook: Notebook,
): NotebookPanel | null {
  return notebooks.find((panel) => panel.content === notebook) ?? null;
}

export default plugin;
