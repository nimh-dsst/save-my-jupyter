import type {
  JupyterFrontEnd,
  JupyterFrontEndPlugin,
} from "@jupyterlab/application";
import {
  ICommandPalette,
  Notification,
} from "@jupyterlab/apputils";
import {
  INotebookTracker,
  type Notebook,
  type NotebookPanel,
} from "@jupyterlab/notebook";
import { ISettingRegistry } from "@jupyterlab/settingregistry";

import { ApiClient } from "./apiClient";
import { mergeTags, parseDirectives } from "./application/directives";
import { triggerSnapshotNotification } from "./application/feedback/notifications";
import { CONNECT_BLOCKED_MESSAGE } from "./application/panel/readiness";
import {
  info as infoStatus,
  warning as warningStatus,
} from "./application/panel/status";
import { NO_NOTEBOOK_CONFIG_MESSAGE } from "./config/starterConfig";
import {
  ExecutionObserver,
  type TriggerRun,
} from "./notebook/executionObserver";
import type { DynamicKernelMetadata } from "./notebook/kernelMetadata";
import {
  addWatchedPath,
  isFinalNotebookCell,
  readNotebookWatchedPaths,
  readTargetOptions,
  readTriggerOptions,
  removeWatchedPath,
  setActiveCellTrigger,
  setupNotebookPanel,
  shouldSnapshotCell,
  syncNotebookTriggerCellIds,
  syncTriggerCellDecorations,
  toggleActiveCellTrigger,
  toggleAllCellsTrigger,
  updateTargetOptions,
} from "./notebook/notebookState";
import {
  buildManualBody,
  buildTriggerBody,
  collectPanelDynamicMetadata,
} from "./notebook/snapshotRequestBodies";
import {
  notebookCellSources,
  triggerRunContentKey,
} from "./notebook/sourceText";
import {
  TriggerDebouncer,
  TRIGGER_SNAPSHOT_DEBOUNCE_MS,
} from "./notebook/triggerDebouncer";
import {
  COMMAND_MARK_CELL_TRIGGER,
  COMMAND_OPEN_PANEL,
  COMMAND_SNAPSHOT,
  COMMAND_TOGGLE_ALL_CELLS_TRIGGER,
  COMMAND_TOGGLE_CELL_TRIGGER,
  COMMAND_UNMARK_CELL_TRIGGER,
  TRIGGER_CONTEXT_SELECTOR,
  triggerCommandLabels,
  triggerToggleLabel,
} from "./notebook/triggers";
import {
  SnapshotPanelController,
  type SnapshotRequestOptions,
} from "./panel/controller";
import { SnapshotPanel } from "./panel/SnapshotPanel";
import { PLUGIN_ID, UserPreferencesStore } from "./settings";

const PALETTE_CATEGORY = "Save My Jupyter";
const PALETTE_COMMANDS = [
  COMMAND_OPEN_PANEL,
  COMMAND_SNAPSHOT,
  COMMAND_TOGGLE_CELL_TRIGGER,
  COMMAND_MARK_CELL_TRIGGER,
  COMMAND_UNMARK_CELL_TRIGGER,
  COMMAND_TOGGLE_ALL_CELLS_TRIGGER,
] as const;
const COMMANDS_WITH_TRIGGER_STATE = [
  COMMAND_MARK_CELL_TRIGGER,
  COMMAND_TOGGLE_ALL_CELLS_TRIGGER,
  COMMAND_TOGGLE_CELL_TRIGGER,
  COMMAND_UNMARK_CELL_TRIGGER,
] as const;
const PANEL_SIDEBAR_RANK = 1000;
const TRIGGER_CONTEXT_MENU_RANK = 1000;
const OPEN_NOTEBOOK_SNAPSHOT_MESSAGE =
  "Open a notebook before creating a snapshot.";

interface PreparedTriggerSnapshot {
  readonly dynamicMetadata: DynamicKernelMetadata;
  readonly options: SnapshotRequestOptions;
  readonly tags: readonly string[];
}

const plugin: JupyterFrontEndPlugin<void> = {
  id: PLUGIN_ID,
  autoStart: true,
  requires: [INotebookTracker],
  optional: [ICommandPalette, ISettingRegistry],
  activate: (
    app: JupyterFrontEnd,
    notebooks: INotebookTracker,
    palette: ICommandPalette | null,
    settingRegistry: ISettingRegistry | null,
  ): void => {
    const api = new ApiClient();
    const controller = new SnapshotPanelController(api);
    const preferences = new UserPreferencesStore(settingRegistry);
    const configuredNotebookPanels = new WeakSet<NotebookPanel>();
    const preparedTriggerRuns = new WeakMap<
      TriggerRun,
      PreparedTriggerSnapshot | null
    >();

    const notifyInfo = (message: string): void => {
      controller.setStatus(infoStatus(message));
    };
    const notifyWarning = (message: string): void => {
      controller.setStatus(warningStatus(message));
    };

    const snapshotPanel = async (
      target: NotebookPanel | null,
    ): Promise<void> => {
      if (target === null) {
        app.shell.activateById(panel.id);
        notifyWarning(OPEN_NOTEBOOK_SNAPSHOT_MESSAGE);
        return;
      }
      controller.setNotebookName(target.context.path);
      const readiness = controller.state.get().readiness;
      if (!readiness.canSnapshot) {
        app.shell.activateById(panel.id);
        controller.setStatus(
          warningStatus(readiness.blockedMessage ?? CONNECT_BLOCKED_MESSAGE),
        );
        return;
      }
      const saved = await saveNotebookForSnapshot(target);
      if (!saved) {
        return;
      }
      const options = controller.snapshotRequestOptions();
      if (options.rememberCommitChoice) {
        await preferences.rememberCommitChoice(options.commitMode);
      }
      const dynamicMetadata = await collectPanelDynamicMetadata(target);
      await controller.snapshot(buildManualBody(target, options, dynamicMetadata));
    };

    const snapshotCurrent = async (): Promise<void> => {
      await snapshotPanel(notebooks.currentWidget);
    };

    const panel = new SnapshotPanel({
      state: controller.state,
      onConnect: () => {
        void controller.toggleAuth();
      },
      onRefresh: () => {
        refreshTriggerUi();
        void controller.refreshAuth();
        void controller.refreshActivity();
      },
      onSnapshot: () => {
        void snapshotCurrent();
      },
      onCheckConfig: () =>
        api.inspectConfig(currentNotebookPath(notebooks)),
      onEnsureConfig: () => api.initConfig(currentNotebookPath(notebooks)),
      onAddWatchedPath: (path) =>
        addWatchedPath(notebooks.currentWidget, path, refreshTriggerUi),
      onRemoveWatchedPath: (path) => {
        removeWatchedPath(notebooks.currentWidget, path);
        refreshTriggerUi();
      },
      onToggleAllCellsTrigger: () => {
        toggleAllCellsTrigger(
          notebooks.currentWidget,
          notifyInfo,
          notifyWarning,
        );
        refreshTriggerUi();
      },
      onToggleCellTrigger: () => {
        toggleActiveCellTrigger(notebooks.currentWidget, notifyWarning);
        refreshTriggerUi();
      },
      onSnapshotOptionsChange: (patch) => {
        controller.updateSnapshotOptions(patch);
        refreshTriggerUi();
      },
      onTargetOptionsChange: (patch) => {
        updateTargetOptions(notebooks.currentWidget, patch);
        controller.setTargetOptions(patch);
        refreshTriggerUi();
      },
    });
    app.shell.add(panel, "right", { rank: PANEL_SIDEBAR_RANK });

    const refreshTriggerUi = (): void => {
      const current = notebooks.currentWidget;
      controller.setNotebookName(
        current !== null ? current.context.path : null,
      );
      controller.setTriggerOptions(readTriggerOptions(current));
      controller.setWatchedPaths(readNotebookWatchedPaths(current));
      controller.setTargetOptions(readTargetOptions(current));
      if (current !== null) {
        const directives = parseDirectives(
          notebookCellSources(current.context.model.toJSON() as unknown),
        );
        controller.setDirectiveDefaults(directives);
        syncTriggerCellDecorations(current);
        syncNotebookTriggerCellIds(current);
        void controller.refreshPreview(
          buildManualBody(current, controller.snapshotRequestOptions()),
        );
      }
      notifyTriggerCommandChanges(app);
    };

    void preferences.load().then((loaded) => {
      controller.setPreferences(loaded);
      preferences.onChange((updated) => {
        controller.setPreferences(updated);
        refreshTriggerUi();
      });
      refreshTriggerUi();
    });
    void controller.refreshAuth();
    void controller.refreshActivity();
    notebooks.currentChanged.connect(refreshTriggerUi);
    notebooks.activeCellChanged.connect(refreshTriggerUi);
    notebooks.selectionChanged.connect(refreshTriggerUi);

    app.commands.addCommand(COMMAND_OPEN_PANEL, {
      label: triggerCommandLabels.openPanel,
      execute: () => {
        app.shell.activateById(panel.id);
      },
    });
    app.commands.addCommand(COMMAND_SNAPSHOT, {
      label: triggerCommandLabels.snapshot,
      execute: () => {
        void snapshotCurrent();
      },
    });
    app.commands.addCommand(COMMAND_TOGGLE_CELL_TRIGGER, {
      label: () =>
        triggerToggleLabel(
          readTriggerOptions(notebooks.currentWidget).activeCell,
        ),
      execute: () => {
        toggleActiveCellTrigger(notebooks.currentWidget, notifyWarning);
        refreshTriggerUi();
      },
    });
    app.commands.addCommand(COMMAND_MARK_CELL_TRIGGER, {
      label: triggerCommandLabels.markCell,
      execute: () => {
        setActiveCellTrigger(notebooks.currentWidget, true, notifyWarning);
        refreshTriggerUi();
      },
    });
    app.commands.addCommand(COMMAND_UNMARK_CELL_TRIGGER, {
      label: triggerCommandLabels.unmarkCell,
      execute: () => {
        setActiveCellTrigger(notebooks.currentWidget, false, notifyWarning);
        refreshTriggerUi();
      },
    });
    app.commands.addCommand(COMMAND_TOGGLE_ALL_CELLS_TRIGGER, {
      isToggled: () =>
        readTriggerOptions(notebooks.currentWidget).allCellsTrigger,
      label: triggerCommandLabels.toggleAllCells,
      execute: () => {
        toggleAllCellsTrigger(
          notebooks.currentWidget,
          notifyInfo,
          notifyWarning,
        );
        refreshTriggerUi();
      },
    });
    if (palette !== null) {
      PALETTE_COMMANDS.forEach((command) => {
        palette.addItem({ command, category: PALETTE_CATEGORY });
      });
    }
    app.contextMenu.addItem({
      command: COMMAND_TOGGLE_CELL_TRIGGER,
      rank: TRIGGER_CONTEXT_MENU_RANK,
      selector: TRIGGER_CONTEXT_SELECTOR,
    });

    const prepareTriggerRun = async (
      run: TriggerRun,
    ): Promise<PreparedTriggerSnapshot | null> => {
      if (preparedTriggerRuns.has(run)) {
        return preparedTriggerRuns.get(run) ?? null;
      }
      const current = findPanel(notebooks, run.notebook);
      if (current === null) {
        preparedTriggerRuns.set(run, null);
        return null;
      }
      const dynamicMetadata = await collectPanelDynamicMetadata(current);
      const options = controller.snapshotRequestOptions();
      const tags = triggerRunTags(current, options, dynamicMetadata);
      const prepared = {
        dynamicMetadata,
        options: { ...options, tags },
        tags,
      };
      preparedTriggerRuns.set(run, prepared);
      return prepared;
    };

    const submitTrigger = async (run: TriggerRun): Promise<void> => {
      const current = findPanel(notebooks, run.notebook);
      if (current === null) {
        preparedTriggerRuns.delete(run);
        return;
      }
      const prepared = await prepareTriggerRun(run);
      preparedTriggerRuns.delete(run);
      if (prepared === null) {
        return;
      }
      if (!(await saveNotebookForSnapshot(current))) {
        return;
      }

      const status = await controller.snapshot(
        buildTriggerBody(
          current,
          run.lastCell,
          run.triggeredCellIds,
          run.runOutcome,
          prepared.options,
          prepared.dynamicMetadata,
        ),
      );
      const notification = triggerSnapshotNotification(status);
      if (notification !== null) {
        const showNotification =
          notification.kind === "success"
            ? Notification.success
            : Notification.error;
        showNotification(notification.message, {
          autoClose: notification.autoClose,
        });
      }
    };
    const triggerDebouncer = new TriggerDebouncer<Notebook, TriggerRun>({
      debounceMs: TRIGGER_SNAPSHOT_DEBOUNCE_MS,
      contentKey: async (run) => {
        const prepared = await prepareTriggerRun(run);
        return prepared === null
          ? null
          : triggerRunContentKey(run, { tags: prepared.tags });
      },
      merge: mergeTriggerRuns,
      onRun: (run) => {
        void submitTrigger(run);
      },
    });
    const scheduleTrigger = (run: TriggerRun): void => {
      triggerDebouncer.schedule(run);
      if (isFinalNotebookCell(run.notebook, run.lastCell)) {
        triggerDebouncer.flush(run.notebook);
      }
    };
    const observer = new ExecutionObserver(shouldSnapshotCell, (run) => {
      scheduleTrigger(run);
    });
    observer.start();
    const idleFallbackPanels = new WeakSet<NotebookPanel>();
    const configureNotebookPanel = (notebookPanel: NotebookPanel): void => {
      setupNotebookPanel(
        notebookPanel,
        configuredNotebookPanels,
        refreshTriggerUi,
      );
      connectKernelIdleFallback(notebookPanel, observer, idleFallbackPanels);
    };
    notebooks.widgetAdded.connect((_tracker, notebookPanel) => {
      configureNotebookPanel(notebookPanel);
    });
    notebooks.forEach((notebookPanel) => {
      configureNotebookPanel(notebookPanel);
    });
    app.shell.disposed.connect(() => {
      observer.dispose();
      triggerDebouncer.dispose();
    });
    refreshTriggerUi();
  },
};

async function saveNotebookForSnapshot(panel: NotebookPanel): Promise<boolean> {
  try {
    await panel.context.save();
    return true;
  } catch {
    return false;
  }
}

function currentNotebookPath(notebooks: INotebookTracker): string {
  const current = notebooks.currentWidget;
  if (current === null) {
    throw new Error(NO_NOTEBOOK_CONFIG_MESSAGE);
  }
  return current.context.path;
}

function findPanel(
  notebooks: INotebookTracker,
  notebook: Notebook,
): NotebookPanel | null {
  return notebooks.find((panel) => panel.content === notebook) ?? null;
}

function connectKernelIdleFallback(
  panel: NotebookPanel,
  observer: ExecutionObserver,
  connectedPanels: WeakSet<NotebookPanel>,
): void {
  if (connectedPanels.has(panel)) {
    return;
  }
  connectedPanels.add(panel);
  panel.context.sessionContext.statusChanged.connect((_sender, status) => {
    if (status === "idle") {
      observer.flushPendingOnIdle(panel.content);
    }
  });
}

function triggerRunTags(
  panel: NotebookPanel,
  options: SnapshotRequestOptions,
  dynamicMetadata: DynamicKernelMetadata,
): string[] {
  const directives = parseDirectives(
    notebookCellSources(panel.context.model.toJSON() as unknown),
  );
  return mergeTags(directives.tags, dynamicMetadata.tags, options.tags);
}

function mergeTriggerRuns(
  previous: TriggerRun,
  next: TriggerRun,
): TriggerRun {
  return {
    notebook: next.notebook,
    lastCell: next.lastCell,
    runOutcome:
      previous.runOutcome === "error" || next.runOutcome === "error"
        ? "error"
        : "success",
    triggeredCellIds: [
      ...new Set([...previous.triggeredCellIds, ...next.triggeredCellIds]),
    ],
  };
}

function notifyTriggerCommandChanges(app: JupyterFrontEnd): void {
  COMMANDS_WITH_TRIGGER_STATE.forEach((command) => {
    if (app.commands.hasCommand(command)) {
      app.commands.notifyCommandChanged(command);
    }
  });
}

export default plugin;
