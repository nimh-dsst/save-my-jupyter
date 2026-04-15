import { formatTagsInput } from "./tags";
import type {
  AuthState,
  CommitMode,
  EffectiveState,
  NotebookExtensionMetadata,
  SnapshotUserMetadata,
  UserPreferences
} from "./types";

export type StatusKind = "error" | "info" | "success" | "warning" | null;

export interface SnapshotPanelViewState {
  activeCellId: string | null;
  activeCellIsTrigger: boolean;
  auth: AuthState;
  authStatusKind: StatusKind;
  authStatusMessage: string | null;
  configStatusKind: StatusKind;
  configStatusMessage: string | null;
  effectiveState: EffectiveState | null;
  isBusy: boolean;
  metadata: NotebookExtensionMetadata;
  notebookPath: string | null;
  rememberCommitChoice: boolean;
  selectedCommitMode: CommitMode;
  statusKind: StatusKind;
  statusMessage: string | null;
  tagsInput: string;
  userMetadata: SnapshotUserMetadata;
}

export interface ActiveCellSnapshotState {
  cellId: string | null;
  isTrigger: boolean;
}

export const DEFAULT_METADATA: NotebookExtensionMetadata = {
  all_cells_trigger: false,
  default_metadata: {},
  enabled: true,
  labarchives_target_notebook: null,
  labarchives_target_root_path: null,
  trigger_cell_ids: [],
  watched_paths: []
};

export const DEFAULT_USER_METADATA: SnapshotUserMetadata = {
  experiment_context: null,
  extra_fields: {},
  notes: null,
  run_label: null,
  tags: []
};

export function normalizeUserMetadata(
  metadata: SnapshotUserMetadata
): SnapshotUserMetadata {
  return {
    ...metadata,
    experiment_context: null
  };
}

export function mergeMetadataDefaults(
  metadata: NotebookExtensionMetadata,
  preferences: UserPreferences
): SnapshotUserMetadata {
  return normalizeUserMetadata({
    experiment_context: null,
    extra_fields: metadata.default_metadata,
    notes: null,
    run_label: preferences.defaultRunLabel,
    tags: preferences.defaultTags
  });
}

export function createInitialViewState(): SnapshotPanelViewState {
  return {
    activeCellId: null,
    activeCellIsTrigger: false,
    auth: {
      pendingRequestId: null,
      status: "unauthenticated",
      storedNotebookNames: [],
      storedUserEmail: null,
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
}

export function buildDetachedViewState(
  current: SnapshotPanelViewState,
  preferences: UserPreferences
): SnapshotPanelViewState {
  return {
    ...current,
    activeCellId: null,
    activeCellIsTrigger: false,
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
  };
}

export interface BuildLoadedViewStateOptions {
  activeCell: ActiveCellSnapshotState;
  current: SnapshotPanelViewState;
  metadata: NotebookExtensionMetadata;
  notebookPath: string;
  preferences: UserPreferences;
  state: EffectiveState;
}

export function buildLoadedViewState({
  activeCell,
  current,
  metadata,
  notebookPath,
  preferences,
  state
}: BuildLoadedViewStateOptions): SnapshotPanelViewState {
  const shouldPreserveDrafts = current.notebookPath === notebookPath;
  return {
    activeCellId: activeCell.cellId,
    activeCellIsTrigger: activeCell.isTrigger,
    auth: state.auth,
    authStatusKind: shouldPreserveDrafts ? current.authStatusKind : null,
    authStatusMessage: shouldPreserveDrafts ? current.authStatusMessage : null,
    configStatusKind: shouldPreserveDrafts ? current.configStatusKind : null,
    configStatusMessage: shouldPreserveDrafts ? current.configStatusMessage : null,
    effectiveState: state,
    isBusy: false,
    metadata,
    notebookPath,
    rememberCommitChoice: shouldPreserveDrafts
      ? current.rememberCommitChoice
      : preferences.rememberCommitChoice,
    selectedCommitMode: shouldPreserveDrafts
      ? current.selectedCommitMode
      : preferences.defaultCommitMode,
    statusKind: shouldPreserveDrafts ? current.statusKind : null,
    statusMessage: shouldPreserveDrafts ? current.statusMessage : null,
    tagsInput: shouldPreserveDrafts
      ? current.tagsInput
      : formatTagsInput(mergeMetadataDefaults(metadata, preferences).tags),
    userMetadata: shouldPreserveDrafts
      ? normalizeUserMetadata(current.userMetadata)
      : mergeMetadataDefaults(metadata, preferences)
  };
}

export interface BuildErrorViewStateOptions {
  activeCell: ActiveCellSnapshotState;
  current: SnapshotPanelViewState;
  error: unknown;
  metadata: NotebookExtensionMetadata;
  notebookPath: string;
  preferences: UserPreferences;
}

export function buildLoadErrorViewState({
  activeCell,
  current,
  error,
  metadata,
  notebookPath,
  preferences
}: BuildErrorViewStateOptions): SnapshotPanelViewState {
  return {
    activeCellId: activeCell.cellId,
    activeCellIsTrigger: activeCell.isTrigger,
    auth: current.auth,
    authStatusKind: current.authStatusKind,
    authStatusMessage: current.authStatusMessage,
    configStatusKind: current.configStatusKind,
    configStatusMessage: current.configStatusMessage,
    effectiveState: null,
    isBusy: false,
    metadata,
    notebookPath,
    rememberCommitChoice: preferences.rememberCommitChoice,
    selectedCommitMode: preferences.defaultCommitMode,
    statusKind: "error",
    statusMessage:
      error instanceof Error
        ? error.message
        : "Failed to load Save My Jupyter state.",
    tagsInput: formatTagsInput(mergeMetadataDefaults(metadata, preferences).tags),
    userMetadata: mergeMetadataDefaults(metadata, preferences)
  };
}
