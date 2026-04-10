import type { JupyterFrontEnd, JupyterFrontEndPlugin } from "@jupyterlab/application";
import { Dialog, ICommandPalette, showDialog } from "@jupyterlab/apputils";
import {
  INotebookTracker,
  NotebookActions,
  type NotebookPanel
} from "@jupyterlab/notebook";
import { ISettingRegistry } from "@jupyterlab/settingregistry";
import { historyIcon, ToolbarButton } from "@jupyterlab/ui-components";

import { ApiClient } from "./apiClient";
import { NotebookMetadataStore } from "./metadata";
import { validateWatchedPath } from "./notebook/pathValidation";
import {
  buildManualSnapshotPayload,
  buildNotebookContextPayload
} from "./notebook/requestBuilders";
import { ExecutionObserver } from "./notebook/triggerHooks";
import {
  requiresPanelSetup
} from "./panelBehavior";
import {
  type SnapshotPanelViewState,
  SnapshotPanel
} from "./panels/SnapshotPanel";
import { UserPreferencesStore } from "./settings";
import type {
  CommitMode,
  NotebookExtensionMetadata,
  SnapshotSubmissionResult,
  SnapshotUserMetadata,
  UserPreferences
} from "./types";

const PLUGIN_ID = "@save-my-jupyter/extension:plugin";
const PANEL_ID = "save-my-jupyter-panel";

const COMMAND_IDS = {
  markCellAsTrigger: "save-my-jupyter:mark-cell-as-trigger",
  openSnapshotSettings: "save-my-jupyter:open-snapshot-settings",
  snapshotNow: "save-my-jupyter:snapshot-now",
  toggleAllCells: "save-my-jupyter:toggle-all-cells",
  unmarkCellAsTrigger: "save-my-jupyter:unmark-cell-as-trigger"
} as const;

const DEFAULT_METADATA: NotebookExtensionMetadata = {
  all_cells_trigger: false,
  default_metadata: {},
  enabled: true,
  labarchives_target_notebook: null,
  labarchives_target_root_path: null,
  trigger_cell_ids: [],
  watched_paths: []
};

const DEFAULT_USER_METADATA: SnapshotUserMetadata = {
  experiment_context: null,
  extra_fields: {},
  notes: null,
  run_label: null,
  tags: []
};

function currentPanel(tracker: INotebookTracker): NotebookPanel {
  const panel = tracker.currentWidget;
  if (panel === null) {
    throw new Error("No active notebook panel.");
  }
  return panel;
}

function toStatusMessage(result: SnapshotSubmissionResult): string {
  switch (result.status) {
    case "accepted":
      return `Snapshot queued as ${result.jobId}.`;
    case "rejected":
      return `Snapshot rejected: ${result.message}`;
  }
}

function mergeMetadataDefaults(
  metadata: NotebookExtensionMetadata,
  preferences: UserPreferences
): SnapshotUserMetadata {
  return {
    experiment_context: preferences.defaultExperimentContext,
    extra_fields: metadata.default_metadata,
    notes: null,
    run_label: preferences.defaultRunLabel,
    tags: preferences.defaultTags
  };
}

class SnapshotPanelModel {
  private hasAutoOpenedPanel = false;
  private viewState: SnapshotPanelViewState = {
    auth: {
      pendingRequestId: null,
      status: "unauthenticated",
      userEmail: null
    },
    effectiveState: null,
    isBusy: false,
    metadata: DEFAULT_METADATA,
    notebookPath: null,
    rememberCommitChoice: false,
    selectedCommitMode: "prompt",
    statusKind: null,
    statusMessage: null,
    userMetadata: DEFAULT_USER_METADATA
  };

  constructor(
    private readonly apiClient: ApiClient,
    private readonly metadataStore: NotebookMetadataStore,
    private readonly openPanel: () => void,
    private readonly preferencesStore: UserPreferencesStore,
    private readonly panelWidget: SnapshotPanel,
    private readonly tracker: INotebookTracker
  ) {}

  initialize(): void {
    this.tracker.currentChanged.connect(() => {
      void this.refresh();
    });

    this.tracker.widgetAdded.connect((_sender, panel) => {
      this.addToolbarButton(panel);
    });

    const initialPanel = this.tracker.currentWidget;
    if (initialPanel !== null) {
      this.addToolbarButton(initialPanel);
    }

    void this.refresh();
  }

  getCommitMode = (): CommitMode => this.resolveCommitMode("this snapshot");

  getUserMetadata = (): SnapshotUserMetadata => this.viewState.userMetadata;

  async refresh(): Promise<void> {
    const panel = this.tracker.currentWidget;
    const preferences = await this.preferencesStore.load();
    if (panel === null) {
      this.updateViewState(() => ({
        ...this.viewState,
        auth: this.viewState.auth,
        effectiveState: null,
        isBusy: false,
        metadata: DEFAULT_METADATA,
        notebookPath: null,
        rememberCommitChoice: preferences.rememberCommitChoice,
        selectedCommitMode: preferences.defaultCommitMode,
        statusKind: null,
        statusMessage: null,
        userMetadata: mergeMetadataDefaults(DEFAULT_METADATA, preferences)
      }));
      return;
    }

    try {
      await panel.context.ready;
      this.ensurePanelIsVisible();
      const state = await this.apiClient.getState(panel.context.path);
      const metadata =
        state.notebookMetadata ?? this.metadataStore.readNotebookMetadata(panel);
      const shouldPreserveDrafts = this.viewState.notebookPath === panel.context.path;
      const nextViewState: SnapshotPanelViewState = {
        auth: state.auth,
        effectiveState: state,
        isBusy: false,
        metadata,
        notebookPath: panel.context.path,
        rememberCommitChoice: shouldPreserveDrafts
          ? this.viewState.rememberCommitChoice
          : preferences.rememberCommitChoice,
        selectedCommitMode: shouldPreserveDrafts
          ? this.viewState.selectedCommitMode
          : preferences.defaultCommitMode,
        statusKind: shouldPreserveDrafts ? this.viewState.statusKind : null,
        statusMessage: shouldPreserveDrafts ? this.viewState.statusMessage : null,
        userMetadata: shouldPreserveDrafts
          ? this.viewState.userMetadata
          : mergeMetadataDefaults(metadata, preferences)
      };
      this.setViewState(nextViewState);
      await this.syncWatchRegistration(panel, nextViewState, { silent: true });
    } catch (error: unknown) {
      const metadata = this.metadataStore.readNotebookMetadata(panel);
      this.setViewState({
        auth: this.viewState.auth,
        effectiveState: null,
        isBusy: false,
        metadata,
        notebookPath: panel.context.path,
        rememberCommitChoice: preferences.rememberCommitChoice,
        selectedCommitMode: preferences.defaultCommitMode,
        statusKind: "error",
        statusMessage:
          error instanceof Error
            ? error.message
            : "Failed to load Save My Jupyter state.",
        userMetadata: mergeMetadataDefaults(metadata, preferences)
      });
    }
  }

  async submitManualSnapshot(): Promise<void> {
    if (requiresPanelSetup(this.viewState.auth)) {
      this.ensurePanelIsVisible();
      this.setStatus(
        "warning",
        "Connect LabArchives before creating a snapshot."
      );
      await showDialog({
        body:
          "Connect LabArchives in the Save My Jupyter tab before creating a snapshot.",
        buttons: [Dialog.okButton({ label: "Open Save My Jupyter" })],
        title: "LabArchives connection required"
      });
      return;
    }

    const panel = currentPanel(this.tracker);
    await panel.context.save();
    const commitMode = this.resolveCommitMode("this manual snapshot");
    const payload = buildManualSnapshotPayload(
      panel,
      this.viewState.metadata,
      commitMode,
      this.viewState.userMetadata
    );

    await this.runBusyTask(async () => {
      const result = await this.apiClient.postSnapshot(payload);
      this.applySubmissionResult(result);
      await this.persistPreferences();
    });
  }

  handleToolbarAction(): void {
    this.openPanel();
    this.setStatus("info", "Use this tab to connect LabArchives and create snapshots.");
  }

  async setAllCellsTrigger(enabled: boolean): Promise<void> {
    const panel = currentPanel(this.tracker);
    const nextMetadata: NotebookExtensionMetadata = {
      ...this.viewState.metadata,
      all_cells_trigger: enabled
    };
    await this.metadataStore.writeNotebookMetadata(panel, nextMetadata);
    this.updateViewState(current => ({
      ...current,
      metadata: nextMetadata,
      statusMessage: enabled
        ? "Every executed cell will trigger snapshots."
        : "Only marked trigger cells will create automatic snapshots."
    }));
  }

  async addWatchedPath(path: string): Promise<void> {
    const validation = validateWatchedPath(path);
    if (!validation.ok) {
      this.updateViewState(current => ({
        ...current,
        statusKind: "warning",
        statusMessage: validation.message
      }));
      return;
    }

    const panel = currentPanel(this.tracker);
    const watchedPaths = Array.from(
      new Set([...this.viewState.metadata.watched_paths, validation.normalizedPath])
    );
    const nextMetadata: NotebookExtensionMetadata = {
      ...this.viewState.metadata,
      watched_paths: watchedPaths
    };
    await this.metadataStore.writeNotebookMetadata(panel, nextMetadata);

    const nextViewState = {
      ...this.viewState,
      metadata: nextMetadata,
      statusKind: "success" as const,
      statusMessage: `Watching ${validation.normalizedPath}.`
    };
    this.setViewState(nextViewState);
    await this.syncWatchRegistration(panel, nextViewState);
  }

  async removeWatchedPath(path: string): Promise<void> {
    const panel = currentPanel(this.tracker);
    const nextMetadata: NotebookExtensionMetadata = {
      ...this.viewState.metadata,
      watched_paths: this.viewState.metadata.watched_paths.filter(
        candidate => candidate !== path
      )
    };
    await this.metadataStore.writeNotebookMetadata(panel, nextMetadata);

    const nextViewState = {
      ...this.viewState,
      metadata: nextMetadata,
      statusKind: "info" as const,
      statusMessage: `Stopped watching ${path}.`
    };
    this.setViewState(nextViewState);
    await this.syncWatchRegistration(panel, nextViewState);
  }

  async setCellTrigger(enabled: boolean): Promise<void> {
    const panel = currentPanel(this.tracker);
    const activeCell = panel.content.activeCell;
    if (activeCell === null) {
      this.updateViewState(current => ({
        ...current,
        statusKind: "warning",
        statusMessage: "Select a cell before changing trigger status."
      }));
      return;
    }

    const metadata = await this.metadataStore.setCellTriggerForPanel(
      panel,
      activeCell,
      enabled
    );
    this.updateViewState(current => ({
      ...current,
      metadata,
      statusKind: "success",
      statusMessage: enabled
        ? `Marked ${activeCell.model.id} as a trigger cell.`
        : `Removed ${activeCell.model.id} from trigger cells.`
    }));
  }

  async startAuthentication(): Promise<void> {
    await this.runBusyTask(async () => {
      const result = await this.apiClient.startAuth();
      if (result.authUrl !== null) {
        window.open(result.authUrl, "_blank", "noopener,noreferrer");
      }
      this.updateViewState(current => ({
        ...current,
        auth: {
          pendingRequestId: result.requestId,
          status: "pending",
          userEmail: current.auth.userEmail
        },
        statusKind: "info",
        statusMessage:
          result.authUrl === null
            ? result.message
            : "Complete the LabArchives sign-in flow in the opened tab, then refresh."
      }));
    });
  }

  async refreshAuth(): Promise<void> {
    const auth = await this.apiClient.getAuthStatus();
    this.updateViewState(current => ({
      ...current,
      auth,
      statusKind: auth.status === "authenticated" ? "success" : "warning",
      statusMessage:
        auth.status === "authenticated"
          ? `Authenticated as ${auth.userEmail ?? "unknown"}.`
          : "Not authenticated with LabArchives yet."
    }));
  }

  setCommitMode(value: CommitMode): void {
    this.updateViewState(current => ({
      ...current,
      selectedCommitMode: value
    }));
    void this.persistPreferences();
  }

  setRememberCommitChoice(value: boolean): void {
    this.updateViewState(current => ({
      ...current,
      rememberCommitChoice: value
    }));
    void this.persistPreferences();
  }

  setTags(value: string): void {
    const tags = value
      .split(",")
      .map(entry => entry.trim())
      .filter(entry => entry !== "");
    this.updateViewState(current => ({
      ...current,
      userMetadata: {
        ...current.userMetadata,
        tags
      }
    }));
    void this.persistPreferences();
  }

  setRunLabel(value: string): void {
    this.updateViewState(current => ({
      ...current,
      userMetadata: {
        ...current.userMetadata,
        run_label: value === "" ? null : value
      }
    }));
    void this.persistPreferences();
  }

  setExperimentContext(value: string): void {
    this.updateViewState(current => ({
      ...current,
      userMetadata: {
        ...current.userMetadata,
        experiment_context: value === "" ? null : value
      }
    }));
    void this.persistPreferences();
  }

  setNotes(value: string): void {
    this.updateViewState(current => ({
      ...current,
      userMetadata: {
        ...current.userMetadata,
        notes: value === "" ? null : value
      }
    }));
  }

  applySubmissionResult(result: SnapshotSubmissionResult): void {
    this.updateViewState(current => ({
      ...current,
      statusKind: result.status === "accepted" ? "success" : "error",
      statusMessage: toStatusMessage(result)
    }));
  }

  private addToolbarButton(panel: NotebookPanel): void {
    if (
      Array.from(panel.toolbar.names()).includes("save-my-jupyter:snapshot")
    ) {
      return;
    }

    panel.toolbar.insertItem(
      10,
      "save-my-jupyter:snapshot",
      new ToolbarButton({
        icon: historyIcon,
        iconLabel: "Save My Jupyter",
        onClick: () => {
          this.handleToolbarAction();
        },
        tooltip: "Open Save My Jupyter"
      })
    );
  }

  private ensurePanelIsVisible(): void {
    if (this.hasAutoOpenedPanel) {
      return;
    }

    this.openPanel();
    this.hasAutoOpenedPanel = true;
  }

  private resolveCommitMode(actionLabel: string): CommitMode {
    if (this.viewState.selectedCommitMode !== "prompt") {
      return this.viewState.selectedCommitMode;
    }

    const shouldCommit = window.confirm(
      `Create a git commit before ${actionLabel}?`
    );
    const resolvedCommitMode: CommitMode = shouldCommit ? "always" : "never";
    if (this.viewState.rememberCommitChoice) {
      this.updateViewState(current => ({
        ...current,
        selectedCommitMode: resolvedCommitMode,
        statusKind: "info",
        statusMessage: `Future snapshots will ${
          resolvedCommitMode === "always" ? "create" : "skip"
        } commits until you change the commit mode.`
      }));
      void this.persistPreferences();
    }
    return resolvedCommitMode;
  }

  private async persistPreferences(): Promise<void> {
    await this.preferencesStore.save({
      defaultCommitMode: this.viewState.selectedCommitMode,
      defaultExperimentContext: this.viewState.userMetadata.experiment_context,
      defaultRunLabel: this.viewState.userMetadata.run_label,
      defaultTags: this.viewState.userMetadata.tags,
      rememberCommitChoice: this.viewState.rememberCommitChoice
    });
  }

  private async runBusyTask(task: () => Promise<void>): Promise<void> {
    this.updateViewState(current => ({
      ...current,
      isBusy: true,
      statusKind: current.statusKind,
      statusMessage: current.statusMessage
    }));
    try {
      await task();
    } catch (error: unknown) {
      this.updateViewState(current => ({
        ...current,
        statusKind: "error",
        statusMessage:
          error instanceof Error ? error.message : "Unexpected snapshot error."
      }));
    } finally {
      this.updateViewState(current => ({
        ...current,
        isBusy: false
      }));
    }
  }

  private async syncWatchRegistration(
    panel: NotebookPanel,
    viewState: SnapshotPanelViewState,
    options: { silent?: boolean } = {}
  ): Promise<void> {
    const result = await this.apiClient.syncWatchRegistration(
      buildNotebookContextPayload(panel, viewState.metadata, null),
      viewState.metadata.watched_paths,
      viewState.selectedCommitMode,
      viewState.userMetadata
    );
    if (options.silent !== true) {
      this.updateViewState(current => ({
        ...current,
        statusKind:
          result.status === "registered"
            ? "success"
            : "info",
        statusMessage:
          result.status === "registered"
            ? `Registered ${String(
                result.registeredWatchPaths.length
              )} watched path(s).`
            : "Removed watched-path registrations."
      }));
    }
  }

  private setViewState(viewState: SnapshotPanelViewState): void {
    this.viewState = viewState;
    this.panelWidget.setViewState(viewState);
  }

  private updateViewState(
    updater: (current: SnapshotPanelViewState) => SnapshotPanelViewState
  ): void {
    this.setViewState(updater(this.viewState));
  }

  private setStatus(
    statusKind: SnapshotPanelViewState["statusKind"],
    statusMessage: string
  ): void {
    this.updateViewState(current => ({
      ...current,
      statusKind,
      statusMessage
    }));
  }
}

const plugin: JupyterFrontEndPlugin<void> = {
  activate: (
    app: JupyterFrontEnd,
    tracker: INotebookTracker,
    palette: ICommandPalette,
    settingRegistry: ISettingRegistry | null
  ): void => {
    const apiClient = new ApiClient();
    const metadataStore = new NotebookMetadataStore();
    const preferencesStore = new UserPreferencesStore(PLUGIN_ID, settingRegistry);
    const snapshotPanel = new SnapshotPanel({
      onAuthenticate: () => {
        void panelModel.startAuthentication();
      },
      onCommitModeChange: value => {
        panelModel.setCommitMode(value);
      },
      onExperimentContextChange: value => {
        panelModel.setExperimentContext(value);
      },
      onNotesChange: value => {
        panelModel.setNotes(value);
      },
      onRefresh: () => {
        void panelModel.refresh();
        void panelModel.refreshAuth();
      },
      onRememberCommitChoiceChange: value => {
        panelModel.setRememberCommitChoice(value);
      },
      onRemoveWatchedPath: path => {
        void panelModel.removeWatchedPath(path);
      },
      onRunLabelChange: value => {
        panelModel.setRunLabel(value);
      },
      onSnapshot: () => {
        void panelModel.submitManualSnapshot();
      },
      onTagsChange: value => {
        panelModel.setTags(value);
      },
      onToggleAllCells: value => {
        void panelModel.setAllCellsTrigger(value);
      },
      onWatchPathSubmit: path => {
        void panelModel.addWatchedPath(path);
      }
    });
    snapshotPanel.id = PANEL_ID;
    snapshotPanel.title.caption = "Save My Jupyter";
    snapshotPanel.title.icon = historyIcon;
    snapshotPanel.title.iconLabel = "Save My Jupyter";
    snapshotPanel.title.label = "Save My Jupyter";
    snapshotPanel.title.closable = true;

    const openPanel = (): void => {
      if (!snapshotPanel.isAttached) {
        const notebookRef = tracker.currentWidget?.id;
        if (notebookRef === undefined) {
          app.shell.add(snapshotPanel, "main");
        } else {
          app.shell.add(snapshotPanel, "main", {
            mode: "split-right",
            ref: notebookRef
          });
        }
      }
      app.shell.activateById(PANEL_ID);
    };

    const panelModel = new SnapshotPanelModel(
      apiClient,
      metadataStore,
      openPanel,
      preferencesStore,
      snapshotPanel,
      tracker
    );
    panelModel.initialize();

    const observer = new ExecutionObserver(
      tracker,
      metadataStore,
      async payload => {
        const result = await apiClient.postSnapshot(payload);
        panelModel.applySubmissionResult(result);
      },
      panelModel.getCommitMode,
      panelModel.getUserMetadata,
      NotebookActions.executed
    );
    observer.attach();

    app.commands.addCommand(COMMAND_IDS.snapshotNow, {
      execute: async () => {
        await panelModel.submitManualSnapshot();
      },
      label: "Snapshot Now"
    });
    app.commands.addCommand(COMMAND_IDS.toggleAllCells, {
      execute: async () => {
        const panel = currentPanel(tracker);
        const metadata = metadataStore.readNotebookMetadata(panel);
        await panelModel.setAllCellsTrigger(!metadata.all_cells_trigger);
      },
      label: "Toggle All Cells As Triggers"
    });
    app.commands.addCommand(COMMAND_IDS.openSnapshotSettings, {
      execute: () => {
        openPanel();
      },
      label: "Open Snapshot Settings"
    });
    app.commands.addCommand(COMMAND_IDS.markCellAsTrigger, {
      execute: async () => {
        await panelModel.setCellTrigger(true);
      },
      label: "Mark Cell As Trigger"
    });
    app.commands.addCommand(COMMAND_IDS.unmarkCellAsTrigger, {
      execute: async () => {
        await panelModel.setCellTrigger(false);
      },
      label: "Unmark Cell As Trigger"
    });

    for (const commandId of Object.values(COMMAND_IDS)) {
      palette.addItem({ command: commandId, category: "Save My Jupyter" });
    }
  },
  autoStart: true,
  id: PLUGIN_ID,
  optional: [ISettingRegistry],
  requires: [INotebookTracker, ICommandPalette]
};

export default plugin;
