import type {
  JupyterFrontEnd,
  JupyterFrontEndPlugin,
} from "@jupyterlab/application";
import {
  Dialog,
  ICommandPalette,
  Notification,
  ToolbarButton,
  showDialog,
} from "@jupyterlab/apputils";
import type { Cell } from "@jupyterlab/cells";
import { PathExt } from "@jupyterlab/coreutils";
import {
  INotebookTracker,
  type Notebook,
  type NotebookPanel,
} from "@jupyterlab/notebook";
import { ISettingRegistry } from "@jupyterlab/settingregistry";

import { ApiClient } from "./apiClient";
import { mergeTags, parseDirectives } from "./application/directives";
import {
  info as infoStatus,
  warning as warningStatus,
} from "./application/panel/status";
import {
  ExecutionObserver,
  type TriggerRun,
} from "./notebook/executionObserver";
import {
  collectDynamicKernelMetadata,
  type DynamicKernelMetadata,
} from "./notebook/kernelMetadata";
import { buildSnapshotRequestBody } from "./notebook/requestBuilders";
import {
  ACTIVE_CELL_TRIGGER_CLASS,
  COMMAND_MARK_CELL_TRIGGER,
  COMMAND_OPEN_PANEL,
  COMMAND_SNAPSHOT,
  COMMAND_TOGGLE_ALL_CELLS_TRIGGER,
  COMMAND_TOGGLE_CELL_TRIGGER,
  COMMAND_UNMARK_CELL_TRIGGER,
  NO_CELL_SELECTED_WARNING,
  SNAPSHOT_TOOLBAR_ITEM,
  TRIGGER_CONTEXT_SELECTOR,
  allCellsConfirmMessage,
  isAllCellsTriggerMetadata,
  isTriggerMetadata,
  shouldDecorateTriggerCell,
  shouldTriggerOnExecution,
  triggerCellIndexForTarget,
  triggerCellState,
  triggerCommandLabels,
  triggerToggleLabel,
  withAllCellsTrigger,
  withSyncedTriggerCellIds,
  withTrigger,
  type TriggerCellState,
} from "./notebook/triggers";
import {
  readWatchedPaths,
  type WatchedPathAddResult,
  withAddedWatchedPath,
  withoutWatchedPath,
} from "./notebook/watchedPaths";
import { SnapshotPanelController } from "./panel/controller";
import type { SnapshotRequestOptions } from "./panel/controller";
import { SnapshotPanel } from "./panel/SnapshotPanel";
import { UserPreferencesStore } from "./settings";
import type { RunOutcome } from "./types";

const PLUGIN_ID = "@save-my-jupyter/extension:plugin";
const PALETTE_CATEGORY = "Save My Jupyter";
const COMMANDS_WITH_TRIGGER_STATE = [
  COMMAND_MARK_CELL_TRIGGER,
  COMMAND_TOGGLE_ALL_CELLS_TRIGGER,
  COMMAND_TOGGLE_CELL_TRIGGER,
  COMMAND_UNMARK_CELL_TRIGGER,
] as const;
const AUTH_REQUIRED_DIALOG_TITLE = "LabArchives connection required";
const AUTH_REQUIRED_DIALOG_BODY =
  "Connect LabArchives in the Save My Jupyter sidebar before creating a snapshot.";
const OPEN_PANEL_BUTTON = "Open Save My Jupyter";
const TRIGGER_STARTED_MESSAGE = "Save My Jupyter trigger snapshot started.";
const EMPTY_DYNAMIC_METADATA: DynamicKernelMetadata = {
  runLabel: null,
  tags: [],
};

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

    const notifyInfo = (message: string): void => {
      controller.setStatus(infoStatus(message));
      Notification.info(message, { autoClose: 3000 });
    };
    const notifyWarning = (message: string): void => {
      controller.setStatus(warningStatus(message));
      Notification.warning(message, { autoClose: 5000 });
    };

    const snapshotPanel = async (
      target: NotebookPanel | null,
    ): Promise<void> => {
      if (target === null) {
        app.shell.activateById(panel.id);
        notifyWarning("Open a notebook before creating a snapshot.");
        return;
      }
      controller.setNotebookName(target.context.path);
      if (!controller.state.get().readiness.canSnapshot) {
        await showAuthRequiredDialog(app, panel.id);
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
    app.shell.add(panel, "right", { rank: 1000 });

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
    notebooks.widgetAdded.connect((_tracker, notebookPanel) => {
      setupNotebookPanel(
        notebookPanel,
        configuredNotebookPanels,
        snapshotPanel,
        refreshTriggerUi,
      );
    });
    notebooks.forEach((notebookPanel) => {
      setupNotebookPanel(
        notebookPanel,
        configuredNotebookPanels,
        snapshotPanel,
        refreshTriggerUi,
      );
    });

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
      [
        COMMAND_OPEN_PANEL,
        COMMAND_SNAPSHOT,
        COMMAND_TOGGLE_CELL_TRIGGER,
        COMMAND_MARK_CELL_TRIGGER,
        COMMAND_UNMARK_CELL_TRIGGER,
        COMMAND_TOGGLE_ALL_CELLS_TRIGGER,
      ].forEach((command) => {
        palette.addItem({ command, category: PALETTE_CATEGORY });
      });
    }
    app.contextMenu.addItem({
      command: COMMAND_TOGGLE_CELL_TRIGGER,
      rank: 1000,
      selector: TRIGGER_CONTEXT_SELECTOR,
    });

    const submitTrigger = async (run: TriggerRun): Promise<void> => {
      const current = findPanel(notebooks, run.notebook);
      if (current !== null) {
        const saved = await saveNotebookForSnapshot(current);
        if (!saved) {
          return;
        }
        Notification.info(TRIGGER_STARTED_MESSAGE, { autoClose: 3000 });
        const options = controller.snapshotRequestOptions();
        const dynamicMetadata = await collectPanelDynamicMetadata(current);
        const status = await controller.snapshot(
          buildTriggerBody(
            current,
            run.lastCell,
            run.triggeredCellIds,
            run.runOutcome,
            options,
            dynamicMetadata,
          ),
        );
        if (status?.kind === "success") {
          Notification.success(status.message, { autoClose: 5000 });
        } else if (status?.kind === "error") {
          Notification.error(status.message, { autoClose: 7000 });
        }
      }
    };
    const observer = new ExecutionObserver(shouldSnapshotCell, (run) => {
      void submitTrigger(run);
    });
    observer.start();
    const idleFallbackPanels = new WeakSet<NotebookPanel>();
    const connectIdleFallback = (notebookPanel: NotebookPanel): void => {
      connectKernelIdleFallback(notebookPanel, observer, idleFallbackPanels);
    };
    notebooks.widgetAdded.connect((_tracker, notebookPanel) => {
      connectIdleFallback(notebookPanel);
    });
    notebooks.forEach((notebookPanel) => {
      connectIdleFallback(notebookPanel);
    });
    app.shell.disposed.connect(() => {
      observer.dispose();
    });
    refreshTriggerUi();
  },
};

function buildManualBody(
  panel: NotebookPanel,
  options: SnapshotRequestOptions,
  dynamicMetadata: DynamicKernelMetadata = EMPTY_DYNAMIC_METADATA,
): Record<string, unknown> {
  const notebookContent = panel.context.model.toJSON() as unknown;
  const directives = parseDirectives(notebookCellSources(notebookContent));
  return buildSnapshotRequestBody({
    source: "manual",
    notebookPath: panel.context.path,
    notebookName: PathExt.basename(panel.context.path),
    documentId: panel.id,
    notebookContent,
    commitMode: options.commitMode,
    runLabel: manualRunLabel(options, dynamicMetadata, directives.runLabel),
    tags: mergeTags(directives.tags, dynamicMetadata.tags, options.tags),
    notes: options.notes,
    extraFields: options.extraFields,
    watchedPaths: readNotebookWatchedPaths(panel),
  });
}

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
    throw new Error("Open a notebook before creating a repo config.");
  }
  return current.context.path;
}

async function showAuthRequiredDialog(
  app: JupyterFrontEnd,
  panelId: string,
): Promise<void> {
  await showDialog({
    body: AUTH_REQUIRED_DIALOG_BODY,
    buttons: [Dialog.okButton({ label: OPEN_PANEL_BUTTON })],
    title: AUTH_REQUIRED_DIALOG_TITLE,
  });
  app.shell.activateById(panelId);
}

function buildTriggerBody(
  panel: NotebookPanel,
  lastCell: Cell,
  triggeredCellIds: readonly string[],
  runOutcome: RunOutcome,
  options: SnapshotRequestOptions,
  dynamicMetadata: DynamicKernelMetadata = EMPTY_DYNAMIC_METADATA,
): Record<string, unknown> {
  const notebookContent = panel.context.model.toJSON() as unknown;
  const directives = parseDirectives(notebookCellSources(notebookContent));
  return buildSnapshotRequestBody({
    source: "trigger_cell",
    notebookPath: panel.context.path,
    notebookName: PathExt.basename(panel.context.path),
    documentId: panel.id,
    triggeringCellId: lastCell.model.id,
    triggeredCellIds,
    notebookContent,
    commitMode: options.commitMode,
    runLabel:
      dynamicMetadata.runLabel ??
      directives.runLabel ??
      firstNonBlankSourceLine(lastCell),
    runOutcome,
    tags: mergeTags(directives.tags, dynamicMetadata.tags, options.tags),
    notes: options.notes,
    extraFields: options.extraFields,
    watchedPaths: readNotebookWatchedPaths(panel),
  });
}

async function collectPanelDynamicMetadata(
  panel: NotebookPanel,
): Promise<DynamicKernelMetadata> {
  return collectDynamicKernelMetadata(
    panel.context.sessionContext.session?.kernel ?? null,
  );
}

function manualRunLabel(
  options: SnapshotRequestOptions,
  dynamicMetadata: DynamicKernelMetadata,
  directiveRunLabel: string | null,
): string | null {
  if (options.runLabelEdited && options.runLabel !== null) {
    return options.runLabel;
  }
  return dynamicMetadata.runLabel ?? options.runLabel ?? directiveRunLabel;
}

function notebookCellSources(notebookContent: unknown): string[] {
  if (
    typeof notebookContent !== "object" ||
    notebookContent === null ||
    !Array.isArray((notebookContent as { cells?: unknown }).cells)
  ) {
    return [];
  }
  return (notebookContent as { cells: unknown[] }).cells.map((cell) => {
    if (typeof cell !== "object" || cell === null) {
      return "";
    }
    return joinSource((cell as { source?: unknown }).source);
  });
}

function firstNonBlankSourceLine(cell: Cell): string | null {
  const source = joinSource(
    (cell.model.toJSON() as { source?: unknown }).source,
  );
  return (
    source
      .split(/\r?\n/)
      .map((line) => line.trim())
      .find((line) => line.length > 0) ?? null
  );
}

function joinSource(source: unknown): string {
  if (typeof source === "string") {
    return source;
  }
  if (Array.isArray(source)) {
    return source.filter((part) => typeof part === "string").join("");
  }
  return "";
}

function shouldSnapshotCell(notebook: Notebook, cell: Cell): boolean {
  return shouldTriggerOnExecution(
    notebook.model?.getMetadata("save_my_jupyter"),
    cell.model.getMetadata("save_my_jupyter"),
  );
}

function findPanel(
  notebooks: INotebookTracker,
  notebook: Notebook,
): NotebookPanel | null {
  return notebooks.find((panel) => panel.content === notebook) ?? null;
}

function readTriggerOptions(panel: NotebookPanel | null): {
  readonly activeCell: TriggerCellState;
  readonly allCellsTrigger: boolean;
} {
  if (panel === null) {
    return { activeCell: "unknown", allCellsTrigger: false };
  }
  return {
    activeCell: readActiveCellTriggerState(panel),
    allCellsTrigger: isAllCellsTriggerMetadata(
      panel.context.model.getMetadata("save_my_jupyter"),
    ),
  };
}

function readNotebookWatchedPaths(panel: NotebookPanel | null): string[] {
  if (panel === null) {
    return [];
  }
  return readWatchedPaths(panel.context.model.getMetadata("save_my_jupyter"));
}

function readTargetOptions(panel: NotebookPanel | null): {
  readonly notebookName: string;
  readonly rootPath: string;
} {
  if (panel === null) {
    return { notebookName: "", rootPath: "" };
  }
  const metadata = asRecord(panel.context.model.getMetadata("save_my_jupyter"));
  return {
    notebookName: asString(metadata["labarchives_target_notebook"]),
    rootPath: asString(metadata["labarchives_target_root_path"]),
  };
}

function addWatchedPath(
  panel: NotebookPanel | null,
  path: string,
  refreshUi: () => void,
): WatchedPathAddResult {
  if (panel === null) {
    return {
      ok: false,
      message: "Open a notebook before adding watched files.",
    };
  }
  const currentMetadata: unknown =
    panel.context.model.getMetadata("save_my_jupyter");
  const result = withAddedWatchedPath(currentMetadata, path);
  if (!result.ok) {
    return result;
  }
  panel.context.model.setMetadata("save_my_jupyter", result.metadata);
  refreshUi();
  return result;
}

function removeWatchedPath(panel: NotebookPanel | null, path: string): void {
  if (panel === null) {
    return;
  }
  const currentMetadata: unknown =
    panel.context.model.getMetadata("save_my_jupyter");
  const next = withoutWatchedPath(currentMetadata, path);
  if (metadataEqual(currentMetadata, next.metadata)) {
    return;
  }
  panel.context.model.setMetadata("save_my_jupyter", next.metadata);
}

function updateTargetOptions(
  panel: NotebookPanel | null,
  patch: Partial<ReturnType<typeof readTargetOptions>>,
): void {
  if (panel === null) {
    return;
  }
  const currentMetadata: unknown =
    panel.context.model.getMetadata("save_my_jupyter");
  const next = { ...asRecord(currentMetadata) };
  setOptionalString(next, "labarchives_target_notebook", patch.notebookName);
  setOptionalString(next, "labarchives_target_root_path", patch.rootPath);
  if (metadataEqual(currentMetadata, next)) {
    return;
  }
  panel.context.model.setMetadata("save_my_jupyter", next);
}

function readActiveCellTriggerState(panel: NotebookPanel): TriggerCellState {
  const cell = panel.content.activeCell;
  if (cell === null) {
    return "unknown";
  }
  return triggerCellState(cell.model.getMetadata("save_my_jupyter"));
}

function toggleActiveCellTrigger(
  panel: NotebookPanel | null,
  notifyWarning: (message: string) => void,
): void {
  const activeState =
    panel !== null ? readActiveCellTriggerState(panel) : "unknown";
  setActiveCellTrigger(panel, activeState !== "marked", notifyWarning);
}

function setActiveCellTrigger(
  panel: NotebookPanel | null,
  trigger: boolean,
  notifyWarning: (message: string) => void,
): void {
  const cell = panel?.content.activeCell ?? null;
  if (panel === null || cell === null) {
    notifyWarning(NO_CELL_SELECTED_WARNING);
    return;
  }
  cell.model.setMetadata(
    "save_my_jupyter",
    withTrigger(cell.model.getMetadata("save_my_jupyter"), trigger),
  );
  syncTriggerCellDecoration(
    cell,
    panel.context.model.getMetadata("save_my_jupyter"),
  );
  syncNotebookTriggerCellIds(panel);
}

function toggleAllCellsTrigger(
  panel: NotebookPanel | null,
  notifyInfo: (message: string) => void,
  notifyWarning: (message: string) => void,
): void {
  if (panel === null) {
    notifyWarning(NO_CELL_SELECTED_WARNING);
    return;
  }
  const metadata: unknown = panel.context.model.getMetadata("save_my_jupyter");
  const enabled = !isAllCellsTriggerMetadata(metadata);
  panel.context.model.setMetadata(
    "save_my_jupyter",
    withAllCellsTrigger(metadata, enabled),
  );
  syncTriggerCellDecorations(panel);
  notifyInfo(allCellsConfirmMessage(enabled));
}

function syncNotebookTriggerCellIds(panel: NotebookPanel): void {
  const cells = panel.content.widgets.map((cell) => ({
    id: cell.model.id,
    trigger: isTriggerMetadata(cell.model.getMetadata("save_my_jupyter")),
  }));
  const currentMetadata: unknown =
    panel.context.model.getMetadata("save_my_jupyter");
  const nextMetadata = withSyncedTriggerCellIds(currentMetadata, cells);
  if (metadataEqual(currentMetadata, nextMetadata)) {
    return;
  }
  panel.context.model.setMetadata("save_my_jupyter", nextMetadata);
}

function metadataEqual(left: unknown, right: Record<string, unknown>): boolean {
  if (typeof left !== "object" || left === null) {
    return Object.keys(right).length === 0;
  }
  return JSON.stringify(left) === JSON.stringify(right);
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? { ...(value as Record<string, unknown>) }
    : {};
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function setOptionalString(
  target: Record<string, unknown>,
  key: string,
  value: string | undefined,
): void {
  if (value === undefined) {
    return;
  }
  const trimmed = value.trim();
  if (trimmed.length === 0) {
    Reflect.deleteProperty(target, key);
    return;
  }
  target[key] = trimmed;
}

function syncTriggerCellDecoration(
  cell: Cell,
  notebookMetadata: unknown,
): void {
  if (
    shouldDecorateTriggerCell(
      notebookMetadata,
      cell.model.getMetadata("save_my_jupyter"),
    )
  ) {
    cell.addClass(ACTIVE_CELL_TRIGGER_CLASS);
  } else {
    cell.removeClass(ACTIVE_CELL_TRIGGER_CLASS);
  }
}

function syncTriggerCellDecorations(panel: NotebookPanel): void {
  const notebookMetadata: unknown =
    panel.context.model.getMetadata("save_my_jupyter");
  panel.content.widgets.forEach((cell) => {
    syncTriggerCellDecoration(cell, notebookMetadata);
  });
}

function setupNotebookPanel(
  panel: NotebookPanel,
  configuredNotebookPanels: WeakSet<NotebookPanel>,
  snapshotPanel: (target: NotebookPanel | null) => Promise<void>,
  refreshTriggerUi: () => void,
): void {
  if (configuredNotebookPanels.has(panel)) {
    return;
  }
  configuredNotebookPanels.add(panel);
  syncTriggerCellDecorations(panel);
  const handleContextMenu = (event: MouseEvent): void => {
    const index = triggerCellIndexForTarget(panel.content.widgets, event.target);
    if (index === null) {
      return;
    }
    panel.content.activeCellIndex = index;
    refreshTriggerUi();
  };
  panel.content.node.addEventListener("contextmenu", handleContextMenu, true);
  panel.disposed.connect(() => {
    panel.content.node.removeEventListener("contextmenu", handleContextMenu, true);
  });
  const inserted = panel.toolbar.insertAfter(
    "run",
    SNAPSHOT_TOOLBAR_ITEM,
    new ToolbarButton({
      label: "Snapshot",
      onClick: () => {
        void snapshotPanel(panel);
      },
      tooltip: "Snapshot with Save My Jupyter",
    }),
  );
  if (!inserted) {
    panel.toolbar.addItem(
      SNAPSHOT_TOOLBAR_ITEM,
      new ToolbarButton({
        label: "Snapshot",
        onClick: () => {
          void snapshotPanel(panel);
        },
        tooltip: "Snapshot with Save My Jupyter",
      }),
    );
  }
  panel.content.modelContentChanged.connect(() => {
    syncTriggerCellDecorations(panel);
    refreshTriggerUi();
  });
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

function notifyTriggerCommandChanges(app: JupyterFrontEnd): void {
  COMMANDS_WITH_TRIGGER_STATE.forEach((command) => {
    if (app.commands.hasCommand(command)) {
      app.commands.notifyCommandChanged(command);
    }
  });
}

export default plugin;
