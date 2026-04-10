import type { JupyterFrontEnd, JupyterFrontEndPlugin } from "@jupyterlab/application";
import { Dialog, ICommandPalette, ToolbarButton, showDialog } from "@jupyterlab/apputils";
import type { Cell } from "@jupyterlab/cells";
import {
  INotebookTracker,
  NotebookActions,
  type NotebookPanel
} from "@jupyterlab/notebook";
import { ISettingRegistry } from "@jupyterlab/settingregistry";
import { historyIcon, tagIcon } from "@jupyterlab/ui-components";

import { ApiClient } from "./apiClient";
import { NotebookMetadataStore } from "./metadata";
import { validateWatchedPath } from "./notebook/pathValidation";
import {
  buildManualSnapshotPayload,
  buildNotebookContextPayload
} from "./notebook/requestBuilders";
import { ExecutionObserver } from "./notebook/triggerHooks";
import { requiresPanelSetup } from "./panelBehavior";
import {
  type SnapshotPanelViewState,
  SnapshotPanel
} from "./panels/SnapshotPanel";
import { UserPreferencesStore } from "./settings";
import { formatTagsInput, parseTagsInput } from "./tags";
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
  toggleSelectedCellTrigger: "save-my-jupyter:toggle-selected-cell-trigger",
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

interface RightSidebarShell {
  expandRight?(): void;
}

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
  private readonly observedPanels = new WeakSet<NotebookPanel>();
  private viewState: SnapshotPanelViewState = {
    activeCellId: null,
    activeCellIsTrigger: false,
    auth: {
      pendingRequestId: null,
      status: "unauthenticated",
      userEmail: null
    },
    authStatusKind: null,
    authStatusMessage: null,
    configStatusKind: null,
    configStatusMessage: null,
    effectiveState: null,
    isBusy: false,
    metadata: DEFAULT_METADATA,
    notebookPath: null,
    rememberCommitChoice: false,
    selectedCommitMode: "prompt",
    statusKind: null,
    statusMessage: null,
    tagsInput: formatTagsInput([]),
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
      this.observePanel(panel);
      this.addToolbarButton(panel);
    });

    const initialPanel = this.tracker.currentWidget;
    if (initialPanel !== null) {
      this.observePanel(initialPanel);
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
        activeCellId: null,
        activeCellIsTrigger: false,
        auth: this.viewState.auth,
        authStatusKind: this.viewState.authStatusKind,
        authStatusMessage: this.viewState.authStatusMessage,
        configStatusKind: this.viewState.configStatusKind,
        configStatusMessage: this.viewState.configStatusMessage,
        effectiveState: null,
        isBusy: false,
        metadata: DEFAULT_METADATA,
        notebookPath: null,
        rememberCommitChoice: preferences.rememberCommitChoice,
        selectedCommitMode: preferences.defaultCommitMode,
        statusKind: null,
        statusMessage: null,
        tagsInput: formatTagsInput(preferences.defaultTags),
        userMetadata: mergeMetadataDefaults(DEFAULT_METADATA, preferences)
      }));
      return;
    }

    try {
      await panel.context.ready;
      const state = await this.apiClient.getState(panel.context.path);
      const metadata =
        state.notebookMetadata ?? this.metadataStore.readNotebookMetadata(panel);
      const activeCellState = this.metadataStore.readActiveCellTriggerState(panel);
      const shouldPreserveDrafts = this.viewState.notebookPath === panel.context.path;
      const nextViewState: SnapshotPanelViewState = {
        activeCellId: activeCellState.cellId,
        activeCellIsTrigger: activeCellState.isTrigger,
        auth: state.auth,
        authStatusKind: shouldPreserveDrafts
          ? this.viewState.authStatusKind
          : null,
        authStatusMessage: shouldPreserveDrafts
          ? this.viewState.authStatusMessage
          : null,
        configStatusKind: shouldPreserveDrafts
          ? this.viewState.configStatusKind
          : null,
        configStatusMessage: shouldPreserveDrafts
          ? this.viewState.configStatusMessage
          : null,
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
        tagsInput: shouldPreserveDrafts
          ? this.viewState.tagsInput
          : formatTagsInput(
              mergeMetadataDefaults(metadata, preferences).tags
            ),
        userMetadata: shouldPreserveDrafts
          ? this.viewState.userMetadata
          : mergeMetadataDefaults(metadata, preferences)
      };
      this.setViewState(nextViewState);
      this.decoratePanelCells(panel);
      await this.syncWatchRegistration(panel, nextViewState, { silent: true });
    } catch (error: unknown) {
      const metadata = this.metadataStore.readNotebookMetadata(panel);
      this.setViewState({
        activeCellId: this.metadataStore.readActiveCellTriggerState(panel).cellId,
        activeCellIsTrigger: this.metadataStore.readActiveCellTriggerState(panel).isTrigger,
        auth: this.viewState.auth,
        authStatusKind: this.viewState.authStatusKind,
        authStatusMessage: this.viewState.authStatusMessage,
        configStatusKind: this.viewState.configStatusKind,
        configStatusMessage: this.viewState.configStatusMessage,
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
        tagsInput: formatTagsInput(mergeMetadataDefaults(metadata, preferences).tags),
        userMetadata: mergeMetadataDefaults(metadata, preferences)
      });
    }
  }

  async submitManualSnapshot(): Promise<void> {
    if (requiresPanelSetup(this.viewState.auth)) {
      this.openPanel();
      this.setStatus(
        "warning",
        "Connect LabArchives before creating a snapshot."
      );
      await showDialog({
        body:
          "Connect LabArchives in the Save My Jupyter sidebar before creating a snapshot.",
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
    if (this.viewState.auth.status === "authenticated") {
      this.setStatus(
        "info",
        "Review the current notebook context and click Snapshot Now when ready."
      );
    } else {
      this.setStatus(
        "warning",
        "Connect LabArchives to enable snapshots for this notebook."
      );
    }
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
    this.decoratePanelCells(panel);
    this.updateViewState(current => ({
      ...current,
      activeCellId: activeCell.model.id,
      activeCellIsTrigger: enabled,
      metadata,
      statusKind: "success",
      statusMessage: enabled
        ? `Marked ${activeCell.model.id} as a trigger cell.`
        : `Removed ${activeCell.model.id} from trigger cells.`
    }));
  }

  async toggleSelectedCellTrigger(): Promise<void> {
    await this.setCellTrigger(!this.viewState.activeCellIsTrigger);
  }

  async startAuthentication(): Promise<void> {
    this.updateViewState(current => ({
      ...current,
      authStatusKind: null,
      authStatusMessage: null,
      isBusy: true
    }));
    try {
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
        authStatusKind: "info",
        authStatusMessage:
          result.authUrl === null
            ? result.message
            : "Complete the LabArchives sign-in flow in the opened tab, then refresh."
      }));
    } catch (error: unknown) {
      this.updateViewState(current => ({
        ...current,
        authStatusKind: "error",
        authStatusMessage:
          error instanceof Error
            ? error.message
            : "Unable to start LabArchives authentication."
      }));
    } finally {
      this.updateViewState(current => ({
        ...current,
        isBusy: false
      }));
    }
  }

  async refreshAuth(): Promise<void> {
    const auth = await this.apiClient.getAuthStatus();
    this.updateViewState(current => ({
      ...current,
      auth,
      authStatusKind: auth.status === "authenticated" ? "success" : "warning",
      authStatusMessage:
        auth.status === "authenticated"
          ? `Authenticated as ${auth.userEmail ?? "unknown"}.`
          : "Not authenticated with LabArchives yet."
    }));
  }

  async generateRepoConfig(): Promise<void> {
    if (this.viewState.notebookPath === null) {
      this.updateViewState(current => ({
        ...current,
        configStatusKind: "warning",
        configStatusMessage: "Open a notebook before creating a repo config."
      }));
      return;
    }

    this.updateViewState(current => ({
      ...current,
      configStatusKind: null,
      configStatusMessage: null,
      isBusy: true
    }));
    try {
      const result = await this.apiClient.generateRepoConfig(this.viewState.notebookPath);
      await this.refresh();
      this.updateViewState(current => ({
        ...current,
        configStatusKind: result.status === "created" ? "success" : "info",
        configStatusMessage:
          result.status === "created"
            ? `Created starter config at ${result.configPath}.`
            : `Config already exists at ${result.configPath}.`
      }));
    } catch (error: unknown) {
      this.updateViewState(current => ({
        ...current,
        configStatusKind: "error",
        configStatusMessage:
          error instanceof Error
            ? error.message
            : "Unable to create the starter config."
      }));
    } finally {
      this.updateViewState(current => ({
        ...current,
        isBusy: false
      }));
    }
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
    const tags = parseTagsInput(value);
    this.updateViewState(current => ({
      ...current,
      tagsInput: value,
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
        className: "smj-ToolbarButton",
        icon: historyIcon,
        label: "Save",
        onClick: () => {
          this.handleToolbarAction();
        },
        tooltip: "Open Save My Jupyter"
      })
    );

    panel.toolbar.insertItem(
      11,
      "save-my-jupyter:toggle-trigger",
      new ToolbarButton({
        className: "smj-ToolbarButton smj-ToolbarButton--trigger",
        icon: tagIcon,
        label: "Trigger",
        onClick: () => {
          void this.toggleSelectedCellTrigger();
        },
        tooltip: "Mark or unmark the selected cell as a trigger"
      })
    );
  }

  private observePanel(panel: NotebookPanel): void {
    if (this.observedPanels.has(panel)) {
      return;
    }

    this.observedPanels.add(panel);
    this.decoratePanelCells(panel);
    panel.content.activeCellChanged.connect(() => {
      if (this.tracker.currentWidget !== panel) {
        return;
      }

      const activeCellState = this.metadataStore.readActiveCellTriggerState(panel);
      this.decoratePanelCells(panel);
      this.updateViewState(current => ({
        ...current,
        activeCellId: activeCellState.cellId,
        activeCellIsTrigger: activeCellState.isTrigger
      }));
    });
  }

  private decoratePanelCells(panel: NotebookPanel): void {
    for (const cell of panel.content.widgets) {
      this.decorateCell(cell);
    }
  }

  private decorateCell(cell: Cell): void {
    const isTrigger = this.metadataStore.readCellMetadata(cell).trigger;
    cell.node.classList.toggle("smj-Cell--trigger", isTrigger);
    if (isTrigger) {
      cell.node.dataset["smjTrigger"] = "true";
      return;
    }

    delete cell.node.dataset["smjTrigger"];
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
      onGenerateRepoConfig: () => {
        void panelModel.generateRepoConfig();
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
      onToggleSelectedCellTrigger: () => {
        void panelModel.toggleSelectedCellTrigger();
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
    snapshotPanel.title.closable = false;

    const openPanel = (): void => {
      if (!snapshotPanel.isAttached) {
        app.shell.add(snapshotPanel, "right", { rank: 1000 });
      }
      const shell = app.shell as RightSidebarShell;
      shell.expandRight?.();
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
    app.commands.addCommand(COMMAND_IDS.toggleSelectedCellTrigger, {
      execute: async () => {
        await panelModel.toggleSelectedCellTrigger();
      },
      label: "Toggle Selected Cell Trigger"
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
