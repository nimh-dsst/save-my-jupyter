import { Dialog, ToolbarButton, showDialog } from "@jupyterlab/apputils";
import type { Cell } from "@jupyterlab/cells";
import type { INotebookTracker, NotebookPanel } from "@jupyterlab/notebook";
import { historyIcon } from "@jupyterlab/ui-components";

import type { ApiClient } from "./apiClient";
import {
  subscribeToAuthCompletionEvents,
  type AuthCompletionEvent,
  type AuthCompletionSubscription,
} from "./authEvents";
import type { NotebookMetadataStore } from "./metadata";
import { syncCellTriggerDecoration } from "./notebook/cellTriggerButtons";
import { validateWatchedPath } from "./notebook/pathValidation";
import {
  buildManualSnapshotPayload,
  buildNotebookContextPayload,
} from "./notebook/requestBuilders";
import { requiresPanelSetup } from "./panelBehavior";
import { formatSnapshotSubmissionStatus } from "./panelFormatting";
import {
  buildDetachedViewState,
  buildLoadedViewState,
  buildLoadErrorViewState,
  normalizeUserMetadata,
  type SnapshotPanelViewState,
} from "./panelState";
import type { UserPreferencesStore } from "./settings";
import { patchSignal, type WritableSignal } from "./signals";
import { parseTagsInput } from "./tags";
import type {
  CommitMode,
  NotebookExtensionMetadata,
  SnapshotSubmissionResult,
  SnapshotUserMetadata,
} from "./types";

const SNAPSHOT_TOOLBAR_ITEM = "save-my-jupyter:snapshot";
const SNAPSHOT_TOOLBAR_INDEX = 10;

type ViewStatePatch = Partial<SnapshotPanelViewState>;
type StatusChannel = "status" | "authStatus" | "configStatus";
type NonNullStatusKind = NonNullable<SnapshotPanelViewState["statusKind"]>;

interface BusyTaskOptions {
  errorChannel?: StatusChannel;
  fallbackErrorMessage?: string;
  startPatch?: ViewStatePatch;
}

const CELL_DECORATION_SELECTOR = ".jp-Cell";

function currentPanel(tracker: INotebookTracker): NotebookPanel {
  const panel = tracker.currentWidget;
  if (panel === null) {
    throw new Error("No active notebook panel.");
  }
  return panel;
}

function toErrorMessage(error: unknown, fallbackMessage: string): string {
  return error instanceof Error ? error.message : fallbackMessage;
}

function createStatusPatch(
  channel: StatusChannel,
  kind: SnapshotPanelViewState["statusKind"],
  message: string | null,
): ViewStatePatch {
  switch (channel) {
    case "authStatus":
      return {
        authStatusKind: kind,
        authStatusMessage: message,
      };
    case "configStatus":
      return {
        configStatusKind: kind,
        configStatusMessage: message,
      };
    case "status":
      return {
        statusKind: kind,
        statusMessage: message,
      };
  }
}

function createAuthStatusPatch(
  auth: SnapshotPanelViewState["auth"],
  unauthenticatedKind: NonNullStatusKind,
  unauthenticatedMessage: string,
): ViewStatePatch {
  return {
    auth,
    ...createStatusPatch(
      "authStatus",
      auth.status === "authenticated" ? "success" : unauthenticatedKind,
      auth.status === "authenticated"
        ? `Authenticated as ${auth.userEmail ?? "unknown"}.`
        : unauthenticatedMessage,
    ),
  };
}

export class SnapshotPanelController {
  private authCompletionSubscription: AuthCompletionSubscription | null = null;
  private readonly observedPanels = new WeakSet<NotebookPanel>();

  constructor(
    private readonly apiClient: ApiClient,
    private readonly metadataStore: NotebookMetadataStore,
    private readonly openPanel: () => void,
    private readonly preferencesStore: UserPreferencesStore,
    private readonly tracker: INotebookTracker,
    private readonly viewStateSignal: WritableSignal<SnapshotPanelViewState>,
  ) {}

  initialize(): void {
    this.authCompletionSubscription ??= subscribeToAuthCompletionEvents(
      (event) => {
        void this.handleAuthCompletionEvent(event);
      },
    );

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

  getUserMetadata = (): SnapshotUserMetadata =>
    normalizeUserMetadata(this.viewState.userMetadata);

  async refresh(): Promise<void> {
    const panel = this.tracker.currentWidget;
    const preferences = await this.preferencesStore.load();
    if (panel === null) {
      this.setViewState(buildDetachedViewState(this.viewState, preferences));
      return;
    }

    try {
      await panel.context.ready;
      const state = await this.apiClient.getState(panel.context.path);
      const metadata =
        state.notebookMetadata ??
        this.metadataStore.readNotebookMetadata(panel);
      const activeCellState =
        this.metadataStore.readActiveCellTriggerState(panel);
      const nextViewState = buildLoadedViewState({
        activeCell: activeCellState,
        current: this.viewState,
        metadata,
        notebookPath: panel.context.path,
        preferences,
        state,
      });
      this.setViewState(nextViewState);
      this.decoratePanelCells(panel);
      await this.syncWatchRegistration(panel, nextViewState, { silent: true });
    } catch (error: unknown) {
      const metadata = this.metadataStore.readNotebookMetadata(panel);
      const activeCellState =
        this.metadataStore.readActiveCellTriggerState(panel);
      this.setViewState(
        buildLoadErrorViewState({
          activeCell: activeCellState,
          current: this.viewState,
          error,
          metadata,
          notebookPath: panel.context.path,
          preferences,
        }),
      );
    }
  }

  async submitManualSnapshot(): Promise<void> {
    if (requiresPanelSetup(this.viewState.auth)) {
      this.openPanel();
      this.setStatus(
        "warning",
        "Connect LabArchives before creating a snapshot.",
      );
      await showDialog({
        body: "Connect LabArchives in the Save My Jupyter sidebar before creating a snapshot.",
        buttons: [Dialog.okButton({ label: "Open Save My Jupyter" })],
        title: "LabArchives connection required",
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
      this.viewState.userMetadata,
    );

    await this.runBusyTask(
      async () => {
        const result = await this.apiClient.postSnapshot(payload);
        this.applySubmissionResult(result);
        await this.persistPreferences();
      },
      {
        fallbackErrorMessage: "Unable to save the snapshot.",
        startPatch: createStatusPatch(
          "status",
          "info",
          "Saving notebook, creating snapshot artifacts, and uploading to LabArchives.",
        ),
      },
    );
  }

  handleToolbarAction(): void {
    this.openPanel();
    this.setStatus(
      this.viewState.auth.status === "authenticated" ? "info" : "warning",
      this.viewState.auth.status === "authenticated"
        ? "Review the current notebook context and click Snapshot Now when ready."
        : "Connect LabArchives to enable snapshots for this notebook.",
    );
  }

  async setAllCellsTrigger(enabled: boolean): Promise<void> {
    const panel = currentPanel(this.tracker);
    const nextMetadata: NotebookExtensionMetadata = {
      ...this.viewState.metadata,
      all_cells_trigger: enabled,
    };
    await this.savePanelMetadata(panel, nextMetadata, {
      statusMessage: enabled
        ? "Every executed cell will trigger snapshots."
        : "Only marked trigger cells will create automatic snapshots.",
    });
  }

  async toggleAllCellsTrigger(): Promise<void> {
    await this.setAllCellsTrigger(!this.viewState.metadata.all_cells_trigger);
  }

  async addWatchedPath(path: string): Promise<void> {
    const validation = validateWatchedPath(path);
    if (!validation.ok) {
      this.setStatus("warning", validation.message);
      return;
    }

    const panel = currentPanel(this.tracker);
    const watchedPaths = Array.from(
      new Set([
        ...this.viewState.metadata.watched_paths,
        validation.normalizedPath,
      ]),
    );
    const nextMetadata: NotebookExtensionMetadata = {
      ...this.viewState.metadata,
      watched_paths: watchedPaths,
    };

    await this.savePanelMetadata(
      panel,
      nextMetadata,
      {
        statusKind: "success",
        statusMessage: `Watching ${validation.normalizedPath}.`,
      },
      { syncWatchRegistration: true },
    );
  }

  async removeWatchedPath(path: string): Promise<void> {
    const panel = currentPanel(this.tracker);
    const nextMetadata: NotebookExtensionMetadata = {
      ...this.viewState.metadata,
      watched_paths: this.viewState.metadata.watched_paths.filter(
        (candidate) => candidate !== path,
      ),
    };

    await this.savePanelMetadata(
      panel,
      nextMetadata,
      {
        statusKind: "info",
        statusMessage: `Stopped watching ${path}.`,
      },
      { syncWatchRegistration: true },
    );
  }

  async setCellTrigger(enabled: boolean): Promise<void> {
    const panel = currentPanel(this.tracker);
    const activeCell = panel.content.activeCell;
    if (activeCell === null) {
      this.setStatus(
        "warning",
        "Select a cell before changing trigger status.",
      );
      return;
    }

    await this.setCellTriggerForCell(panel, activeCell, enabled);
  }

  async toggleSelectedCellTrigger(): Promise<void> {
    await this.setCellTrigger(!this.viewState.activeCellIsTrigger);
  }

  async startAuthentication(): Promise<void> {
    await this.runBusyTask(
      async () => {
        const result = await this.apiClient.startAuth();
        this.updateViewState((current) => ({
          ...current,
          auth: {
            pendingRequestId: result.requestId,
            status: "pending",
            storedNotebookNames: current.auth.storedNotebookNames,
            storedUserEmail: current.auth.storedUserEmail,
            userEmail: current.auth.userEmail,
          },
          ...createStatusPatch(
            "authStatus",
            "info",
            result.authUrl === null
              ? result.message
              : "Complete the LabArchives sign-in flow in the opened tab. This panel will update automatically.",
          ),
        }));
        if (result.authUrl !== null) {
          window.open(result.authUrl, "_blank", "noopener,noreferrer");
        }
      },
      {
        errorChannel: "authStatus",
        fallbackErrorMessage: "Unable to start LabArchives authentication.",
        startPatch: createStatusPatch("authStatus", null, null),
      },
    );
  }

  async refreshAuth(): Promise<void> {
    const auth = await this.apiClient.getAuthStatus();
    this.patchViewState(
      createAuthStatusPatch(
        auth,
        "warning",
        "Not authenticated with LabArchives yet.",
      ),
    );
  }

  async signOut(): Promise<void> {
    await this.runBusyTask(
      async () => {
        const auth = await this.apiClient.logout();
        this.patchViewState(
          createAuthStatusPatch(auth, "info", "Signed out of LabArchives."),
        );
      },
      {
        errorChannel: "authStatus",
        fallbackErrorMessage: "Unable to sign out of LabArchives.",
        startPatch: createStatusPatch("authStatus", "info", "Signing out..."),
      },
    );
  }

  async generateRepoConfig(): Promise<void> {
    const notebookPath = this.viewState.notebookPath;
    if (notebookPath === null) {
      this.setStatus(
        "warning",
        "Open a notebook before creating a repo config.",
        "configStatus",
      );
      return;
    }

    await this.runBusyTask(
      async () => {
        const result = await this.apiClient.generateRepoConfig(notebookPath);
        await this.refresh();
        this.setStatus(
          result.status === "created" ? "success" : "info",
          result.status === "created"
            ? `Created starter config at ${result.configPath}.`
            : `Config already exists at ${result.configPath}.`,
          "configStatus",
        );
      },
      {
        errorChannel: "configStatus",
        fallbackErrorMessage: "Unable to create the starter config.",
        startPatch: createStatusPatch("configStatus", null, null),
      },
    );
  }

  setCommitMode(value: CommitMode): void {
    this.patchViewState({
      selectedCommitMode: value,
    });
    void this.persistPreferences();
  }

  setRememberCommitChoice(value: boolean): void {
    this.patchViewState({
      rememberCommitChoice: value,
    });
    void this.persistPreferences();
  }

  setTags(value: string): void {
    const tags = parseTagsInput(value);
    this.updateViewState((current) => ({
      ...current,
      tagsInput: value,
      userMetadata: {
        ...current.userMetadata,
        tags,
      },
    }));
    void this.persistPreferences();
  }

  setRunLabel(value: string): void {
    this.updateViewState((current) => ({
      ...current,
      userMetadata: {
        ...current.userMetadata,
        run_label: value === "" ? null : value,
      },
    }));
    void this.persistPreferences();
  }

  setNotes(value: string): void {
    this.updateViewState((current) => ({
      ...current,
      userMetadata: normalizeUserMetadata({
        ...current.userMetadata,
        notes: value === "" ? null : value,
      }),
    }));
  }

  applySubmissionResult(result: SnapshotSubmissionResult): void {
    this.setStatus(
      result.status === "accepted" ? "success" : "error",
      formatSnapshotSubmissionStatus(result),
    );
  }

  applySubmissionError(error: unknown, fallbackMessage: string): void {
    this.setStatus("error", toErrorMessage(error, fallbackMessage));
  }

  private get viewState(): SnapshotPanelViewState {
    return this.viewStateSignal.get();
  }

  private async handleAuthCompletionEvent(
    event: AuthCompletionEvent,
  ): Promise<void> {
    if (this.viewState.auth.pendingRequestId !== event.requestId) {
      return;
    }

    try {
      const auth = await this.apiClient.getAuthStatus();
      this.patchViewState(
        createAuthStatusPatch(
          auth,
          event.status === "error" ? "error" : "warning",
          event.message ?? "LabArchives authentication did not complete.",
        ),
      );
    } catch (error: unknown) {
      this.setStatus(
        "error",
        toErrorMessage(
          error,
          "Unable to refresh LabArchives authentication status.",
        ),
        "authStatus",
      );
    }
  }

  private addToolbarButton(panel: NotebookPanel): void {
    if (Array.from(panel.toolbar.names()).includes(SNAPSHOT_TOOLBAR_ITEM)) {
      return;
    }

    panel.toolbar.insertItem(
      SNAPSHOT_TOOLBAR_INDEX,
      SNAPSHOT_TOOLBAR_ITEM,
      new ToolbarButton({
        className: "smj-ToolbarButton",
        icon: historyIcon,
        label: "Save",
        onClick: () => {
          this.handleToolbarAction();
        },
        tooltip: "Open Save My Jupyter",
      }),
    );
  }

  private observePanel(panel: NotebookPanel): void {
    if (this.observedPanels.has(panel)) {
      return;
    }

    this.observedPanels.add(panel);
    let pendingDecorationFrame: number | null = null;
    const scheduleDecoration = (): void => {
      if (panel.isDisposed || pendingDecorationFrame !== null) {
        return;
      }

      pendingDecorationFrame = window.requestAnimationFrame(() => {
        pendingDecorationFrame = null;
        if (!panel.isDisposed) {
          this.decoratePanelCells(panel);
        }
      });
    };

    this.decoratePanelCells(panel);
    scheduleDecoration();
    const observer = new MutationObserver((mutations) => {
      if (shouldRefreshCellDecorations(mutations)) {
        scheduleDecoration();
      }
    });
    observer.observe(panel.content.node, {
      attributeFilter: ["class"],
      attributes: true,
      childList: true,
      subtree: true,
    });
    panel.disposed.connect(() => {
      observer.disconnect();
      if (pendingDecorationFrame !== null) {
        window.cancelAnimationFrame(pendingDecorationFrame);
        pendingDecorationFrame = null;
      }
    });
    panel.content.activeCellChanged.connect(() => {
      if (this.tracker.currentWidget !== panel) {
        return;
      }

      const activeCellState =
        this.metadataStore.readActiveCellTriggerState(panel);
      this.decoratePanelCells(panel);
      this.patchViewState({
        activeCellId: activeCellState.cellId,
        activeCellIsTrigger: activeCellState.isTrigger,
      });
    });
  }

  private decoratePanelCells(panel: NotebookPanel): void {
    for (const cell of panel.content.widgets) {
      this.decorateCell(cell);
    }
  }

  private decorateCell(cell: Cell): void {
    const isTrigger = this.metadataStore.readCellMetadata(cell).trigger;
    syncCellTriggerDecoration(cell, isTrigger);
  }

  async toggleCellTriggerForCell(
    panel: NotebookPanel,
    cell: Cell,
  ): Promise<void> {
    const cellIndex = panel.content.widgets.indexOf(cell);
    if (cellIndex === -1) {
      return;
    }

    panel.content.activeCellIndex = cellIndex;
    const isTrigger = this.metadataStore.readCellMetadata(cell).trigger;
    await this.setCellTriggerForCell(panel, cell, !isTrigger);
  }

  private async setCellTriggerForCell(
    panel: NotebookPanel,
    cell: Cell,
    enabled: boolean,
  ): Promise<void> {
    const metadata = await this.metadataStore.setCellTriggerForPanel(
      panel,
      cell,
      enabled,
    );
    this.decoratePanelCells(panel);
    this.patchViewState({
      activeCellId: cell.model.id,
      activeCellIsTrigger: enabled,
      metadata,
      statusKind: "success",
      statusMessage: enabled
        ? `Marked ${cell.model.id} as a trigger cell.`
        : `Removed ${cell.model.id} from trigger cells.`,
    });
  }

  private resolveCommitMode(actionLabel: string): CommitMode {
    if (this.viewState.selectedCommitMode !== "prompt") {
      return this.viewState.selectedCommitMode;
    }

    const resolvedCommitMode: CommitMode = window.confirm(
      `Create a git commit before ${actionLabel}?`,
    )
      ? "always"
      : "never";
    if (this.viewState.rememberCommitChoice) {
      this.patchViewState({
        selectedCommitMode: resolvedCommitMode,
        ...createStatusPatch(
          "status",
          "info",
          `Future snapshots will ${
            resolvedCommitMode === "always" ? "create" : "skip"
          } commits until you change the commit mode.`,
        ),
      });
      void this.persistPreferences();
    }
    return resolvedCommitMode;
  }

  private async persistPreferences(): Promise<void> {
    await this.preferencesStore.save({
      defaultCommitMode: this.viewState.selectedCommitMode,
      defaultRunLabel: this.viewState.userMetadata.run_label,
      defaultTags: this.viewState.userMetadata.tags,
      rememberCommitChoice: this.viewState.rememberCommitChoice,
    });
  }

  private async runBusyTask(
    task: () => Promise<void>,
    options: BusyTaskOptions = {},
  ): Promise<void> {
    this.patchViewState({
      ...options.startPatch,
      isBusy: true,
    });
    try {
      await task();
    } catch (error: unknown) {
      this.setStatus(
        "error",
        toErrorMessage(
          error,
          options.fallbackErrorMessage ?? "Unexpected snapshot error.",
        ),
        options.errorChannel,
      );
    } finally {
      this.patchViewState({
        isBusy: false,
      });
    }
  }

  private async savePanelMetadata(
    panel: NotebookPanel,
    metadata: NotebookExtensionMetadata,
    patch: ViewStatePatch = {},
    options: { syncWatchRegistration?: boolean } = {},
  ): Promise<void> {
    await this.metadataStore.writeNotebookMetadata(panel, metadata);
    const nextViewState = {
      ...this.viewState,
      ...patch,
      metadata,
    };
    this.setViewState(nextViewState);
    if (options.syncWatchRegistration === true) {
      await this.syncWatchRegistration(panel, nextViewState);
    }
  }

  private async syncWatchRegistration(
    panel: NotebookPanel,
    viewState: SnapshotPanelViewState,
    options: { silent?: boolean } = {},
  ): Promise<void> {
    const result = await this.apiClient.syncWatchRegistration(
      buildNotebookContextPayload(panel, viewState.metadata, null),
      viewState.metadata.watched_paths,
      viewState.selectedCommitMode,
      viewState.userMetadata,
    );
    if (options.silent !== true) {
      this.patchViewState({
        statusKind: result.status === "registered" ? "success" : "info",
        statusMessage:
          result.status === "registered"
            ? `Registered ${String(
                result.registeredWatchPaths.length,
              )} watched path(s).`
            : "Removed watched-path registrations.",
      });
    }
  }

  private setViewState(viewState: SnapshotPanelViewState): void {
    this.viewStateSignal.set(viewState);
  }

  private updateViewState(
    updater: (current: SnapshotPanelViewState) => SnapshotPanelViewState,
  ): void {
    this.viewStateSignal.update(updater);
  }

  private patchViewState(patch: ViewStatePatch): void {
    patchSignal(this.viewStateSignal, patch);
  }

  private setStatus(
    statusKind: SnapshotPanelViewState["statusKind"],
    statusMessage: string | null,
    channel: StatusChannel = "status",
  ): void {
    this.patchViewState(createStatusPatch(channel, statusKind, statusMessage));
  }
}

function shouldRefreshCellDecorations(mutations: MutationRecord[]): boolean {
  return mutations.some((mutation) => {
    if (mutation.type === "attributes") {
      return nodeCanAffectCellDecorations(mutation.target);
    }

    if (nodeCanAffectCellDecorations(mutation.target)) {
      return true;
    }

    return (
      Array.from(mutation.addedNodes).some(nodeCanAffectCellDecorations) ||
      Array.from(mutation.removedNodes).some(nodeCanAffectCellDecorations)
    );
  });
}

function nodeCanAffectCellDecorations(node: Node): boolean {
  if (!(node instanceof Element)) {
    return false;
  }

  return (
    node.matches(CELL_DECORATION_SELECTOR) ||
    node.querySelector(CELL_DECORATION_SELECTOR) !== null
  );
}
