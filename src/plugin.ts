import type {
  JupyterFrontEnd,
  JupyterFrontEndPlugin,
} from "@jupyterlab/application";
import { ICommandPalette, Notification } from "@jupyterlab/apputils";
import type { Cell } from "@jupyterlab/cells";
import {
  INotebookTracker,
  NotebookActions,
  type NotebookPanel,
} from "@jupyterlab/notebook";
import { ISettingRegistry } from "@jupyterlab/settingregistry";
import { historyIcon } from "@jupyterlab/ui-components";

import { ApiClient } from "./apiClient";
import { NotebookMetadataStore } from "./metadata";
import { ExecutionObserver } from "./notebook/triggerHooks";
import { SnapshotPanelController } from "./panelController";
import { formatSnapshotSubmissionStatus } from "./panelFormatting";
import {
  SnapshotPanel,
  type SnapshotPanelCallbacks,
} from "./panels/SnapshotPanel";
import {
  createInitialViewState,
  type SnapshotPanelViewState,
} from "./panelState";
import { UserPreferencesStore } from "./settings";
import { createSignal } from "./signals";

const PLUGIN_ID = "@save-my-jupyter/extension:plugin";
const PANEL_ID = "save-my-jupyter-panel";
const PANEL_TITLE = "Save My Jupyter";
const PALETTE_CATEGORY = "Save My Jupyter";
const NOTEBOOK_CELL_CONTEXT_SELECTOR = ".jp-Notebook .jp-Cell";

const COMMAND_IDS = {
  contextMenuToggleCellTrigger:
    "save-my-jupyter:context-menu-toggle-cell-trigger",
  markCellAsTrigger: "save-my-jupyter:mark-cell-as-trigger",
  openSnapshotSettings: "save-my-jupyter:open-snapshot-settings",
  snapshotNow: "save-my-jupyter:snapshot-now",
  toggleSelectedCellTrigger: "save-my-jupyter:toggle-selected-cell-trigger",
  toggleAllCells: "save-my-jupyter:toggle-all-cells",
  unmarkCellAsTrigger: "save-my-jupyter:unmark-cell-as-trigger",
} as const;

interface RightSidebarShell {
  expandRight?(): void;
}

interface CommandDefinition {
  execute: () => void | Promise<void>;
  id: string;
  label: string;
}

interface ContextMenuCellTarget {
  cell: Cell;
  panel: NotebookPanel;
}

function fireAndForget<Args extends unknown[]>(
  action: (...args: Args) => Promise<void>,
): (...args: Args) => void {
  return (...args) => {
    void action(...args);
  };
}

function toErrorMessage(error: unknown, fallbackMessage: string): string {
  return error instanceof Error ? error.message : fallbackMessage;
}

function configureSnapshotPanel(snapshotPanel: SnapshotPanel): SnapshotPanel {
  snapshotPanel.id = PANEL_ID;
  snapshotPanel.title.caption = PANEL_TITLE;
  snapshotPanel.title.icon = historyIcon;
  snapshotPanel.title.iconLabel = PANEL_TITLE;
  snapshotPanel.title.label = PANEL_TITLE;
  snapshotPanel.title.closable = false;
  return snapshotPanel;
}

function findContextMenuCellTarget(
  app: JupyterFrontEnd,
  tracker: INotebookTracker,
): ContextMenuCellTarget | null {
  const cellNode = app.contextMenuHitTest((node) =>
    node.classList.contains("jp-Cell"),
  );
  if (cellNode === undefined) {
    return null;
  }

  const panel = tracker.find((candidate) =>
    candidate.content.node.contains(cellNode),
  );
  if (panel === undefined) {
    return null;
  }

  const cell = panel.content.widgets.find(
    (candidate) => candidate.node === cellNode,
  );
  if (cell === undefined) {
    return null;
  }

  return { cell, panel };
}

function createOpenPanel(
  app: JupyterFrontEnd,
  snapshotPanel: SnapshotPanel,
): () => void {
  return () => {
    if (!snapshotPanel.isAttached) {
      app.shell.add(snapshotPanel, "right", { rank: 1000 });
    }

    const shell = app.shell as RightSidebarShell;
    shell.expandRight?.();
    app.shell.activateById(PANEL_ID);
  };
}

function createPanelCallbacks(
  panelController: () => SnapshotPanelController,
): SnapshotPanelCallbacks {
  const refresh = fireAndForget(async () => {
    await Promise.all([
      panelController().refresh(),
      panelController().refreshAuth(),
    ]);
  });

  return {
    onAuthenticate: fireAndForget(async () => {
      await panelController().startAuthentication();
    }),
    onCommitModeChange: (value) => {
      panelController().setCommitMode(value);
    },
    onGenerateRepoConfig: fireAndForget(async () => {
      await panelController().generateRepoConfig();
    }),
    onNotesChange: (value) => {
      panelController().setNotes(value);
    },
    onRefresh: refresh,
    onRememberCommitChoiceChange: (value) => {
      panelController().setRememberCommitChoice(value);
    },
    onRemoveWatchedPath: fireAndForget(async (path) => {
      await panelController().removeWatchedPath(path);
    }),
    onRunLabelChange: (value) => {
      panelController().setRunLabel(value);
    },
    onSignOut: fireAndForget(async () => {
      await panelController().signOut();
    }),
    onSnapshot: fireAndForget(async () => {
      await panelController().submitManualSnapshot();
    }),
    onTagsChange: (value) => {
      panelController().setTags(value);
    },
    onToggleAllCells: fireAndForget(async (value) => {
      await panelController().setAllCellsTrigger(value);
    }),
    onWatchPathSubmit: fireAndForget(async (path) => {
      await panelController().addWatchedPath(path);
    }),
  };
}

function createCommandDefinitions(
  openPanel: () => void,
  panelController: SnapshotPanelController,
): readonly CommandDefinition[] {
  return [
    {
      execute: async () => {
        await panelController.submitManualSnapshot();
      },
      id: COMMAND_IDS.snapshotNow,
      label: "Snapshot Now",
    },
    {
      execute: async () => {
        await panelController.toggleSelectedCellTrigger();
      },
      id: COMMAND_IDS.toggleSelectedCellTrigger,
      label: "Toggle Selected Cell Trigger",
    },
    {
      execute: async () => {
        await panelController.toggleAllCellsTrigger();
      },
      id: COMMAND_IDS.toggleAllCells,
      label: "Toggle All Cells As Triggers",
    },
    {
      execute: openPanel,
      id: COMMAND_IDS.openSnapshotSettings,
      label: "Open Snapshot Settings",
    },
    {
      execute: async () => {
        await panelController.setCellTrigger(true);
      },
      id: COMMAND_IDS.markCellAsTrigger,
      label: "Mark Cell As Trigger",
    },
    {
      execute: async () => {
        await panelController.setCellTrigger(false);
      },
      id: COMMAND_IDS.unmarkCellAsTrigger,
      label: "Unmark Cell As Trigger",
    },
  ];
}

const plugin: JupyterFrontEndPlugin<void> = {
  activate: (
    app: JupyterFrontEnd,
    tracker: INotebookTracker,
    palette: ICommandPalette,
    settingRegistry: ISettingRegistry | null,
  ): void => {
    const apiClient = new ApiClient();
    const metadataStore = new NotebookMetadataStore();
    const preferencesStore = new UserPreferencesStore(
      PLUGIN_ID,
      settingRegistry,
    );
    const viewStateSignal = createSignal<SnapshotPanelViewState>(
      createInitialViewState(),
    );
    const panelControllerRef: { current: SnapshotPanelController | null } = {
      current: null,
    };
    const getPanelController = (): SnapshotPanelController => {
      const panelController = panelControllerRef.current;
      if (panelController === null) {
        throw new Error("Snapshot panel controller is not initialized.");
      }
      return panelController;
    };

    const snapshotPanel = configureSnapshotPanel(
      new SnapshotPanel(
        createPanelCallbacks(getPanelController),
        viewStateSignal,
      ),
    );
    const openPanel = createOpenPanel(app, snapshotPanel);

    const panelController = new SnapshotPanelController(
      apiClient,
      metadataStore,
      openPanel,
      preferencesStore,
      tracker,
      viewStateSignal,
    );
    panelControllerRef.current = panelController;
    panelController.initialize();

    const observer = new ExecutionObserver(
      tracker,
      metadataStore,
      async (payload) => {
        Notification.info("Save My Jupyter trigger snapshot started.", {
          autoClose: 3000,
        });
        try {
          const result = await apiClient.postSnapshot(payload);
          panelController.applySubmissionResult(result);
          Notification.success(formatSnapshotSubmissionStatus(result), {
            autoClose: 5000,
          });
        } catch (error: unknown) {
          const message = toErrorMessage(
            error,
            "Save My Jupyter trigger snapshot failed.",
          );
          panelController.applySubmissionError(error, message);
          Notification.error(message, { autoClose: 7000 });
        }
      },
      panelController.getCommitMode,
      panelController.getUserMetadata,
      NotebookActions.executed,
    );
    observer.attach();

    for (const command of createCommandDefinitions(
      openPanel,
      panelController,
    )) {
      app.commands.addCommand(command.id, {
        execute: command.execute,
        label: command.label,
      });
      palette.addItem({ command: command.id, category: PALETTE_CATEGORY });
    }

    app.commands.addCommand(COMMAND_IDS.contextMenuToggleCellTrigger, {
      execute: async () => {
        const target = findContextMenuCellTarget(app, tracker);
        if (target === null) {
          await panelController.toggleSelectedCellTrigger();
          return;
        }

        await panelController.toggleCellTriggerForCell(
          target.panel,
          target.cell,
        );
      },
      isEnabled: () =>
        findContextMenuCellTarget(app, tracker) !== null ||
        tracker.currentWidget !== null,
      label: () => {
        const target = findContextMenuCellTarget(app, tracker);
        if (target === null) {
          return "Toggle Cell Trigger";
        }

        return metadataStore.readCellMetadata(target.cell).trigger
          ? "Unmark Cell As Trigger"
          : "Mark Cell As Trigger";
      },
    });
    app.contextMenu.addItem({
      command: COMMAND_IDS.contextMenuToggleCellTrigger,
      rank: 12,
      selector: NOTEBOOK_CELL_CONTEXT_SELECTOR,
    });
  },
  autoStart: true,
  id: PLUGIN_ID,
  optional: [ISettingRegistry],
  requires: [INotebookTracker, ICommandPalette],
};

export default plugin;
