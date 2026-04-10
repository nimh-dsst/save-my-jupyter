import { ReactWidget } from "@jupyterlab/apputils";
import React from "react";

import { getSnapshotAvailability } from "../panelBehavior";
import type {
  AuthState,
  CommitMode,
  EffectiveState,
  NotebookExtensionMetadata,
  SnapshotUserMetadata
} from "../types";

export interface SnapshotPanelViewState {
  auth: AuthState;
  effectiveState: EffectiveState | null;
  isBusy: boolean;
  metadata: NotebookExtensionMetadata;
  notebookPath: string | null;
  rememberCommitChoice: boolean;
  selectedCommitMode: CommitMode;
  statusKind: "error" | "info" | "success" | "warning" | null;
  statusMessage: string | null;
  userMetadata: SnapshotUserMetadata;
}

export interface SnapshotPanelCallbacks {
  onAuthenticate(): void;
  onCommitModeChange(value: CommitMode): void;
  onExperimentContextChange(value: string): void;
  onNotesChange(value: string): void;
  onRefresh(): void;
  onRememberCommitChoiceChange(value: boolean): void;
  onRemoveWatchedPath(path: string): void;
  onRunLabelChange(value: string): void;
  onSnapshot(): void;
  onTagsChange(value: string): void;
  onToggleAllCells(value: boolean): void;
  onWatchPathSubmit(path: string): void;
}

export interface SnapshotPanelProps {
  callbacks: SnapshotPanelCallbacks;
  viewState: SnapshotPanelViewState;
}

function SnapshotPanelBody({
  callbacks,
  viewState
}: SnapshotPanelProps): React.JSX.Element {
  const [watchPathInput, setWatchPathInput] = React.useState("");

  React.useEffect(() => {
    setWatchPathInput("");
  }, [viewState.notebookPath]);

  const watchedPathSummary =
    viewState.effectiveState?.effectiveConfig?.watchedPaths ??
    viewState.metadata.watched_paths;

  const tagsValue = viewState.userMetadata.tags.join(", ");
  const authLabel =
    viewState.auth.status === "authenticated"
      ? `Authenticated as ${viewState.auth.userEmail ?? "unknown"}`
      : viewState.auth.status === "pending"
        ? "Authentication pending"
        : "Not authenticated";

  const statusClassName =
    viewState.statusKind === null
      ? null
      : `smj-SnapshotPanel__status smj-SnapshotPanel__status--${viewState.statusKind}`;
  const snapshotAvailability = getSnapshotAvailability(
    viewState.auth,
    viewState.notebookPath,
    viewState.isBusy
  );

  return (
    <section className="smj-SnapshotPanel__body">
      <div className="smj-SnapshotPanel__header">
        <h2>Save My Jupyter</h2>
        <p>{viewState.notebookPath ?? "Open a notebook to configure snapshots."}</p>
        <div className="smj-SnapshotPanel__headerMeta">
          <span className="smj-SnapshotPanel__chip">Notebook workflow snapshots</span>
          <span className="smj-SnapshotPanel__chip">{authLabel}</span>
        </div>
      </div>

      <section className="smj-SnapshotPanel__section">
        <div className="smj-SnapshotPanel__sectionHeader">
          <strong>LabArchives</strong>
          <button
            className="jp-mod-styled"
            type="button"
            onClick={() => {
              callbacks.onAuthenticate();
            }}
          >
            Connect
          </button>
        </div>
        <p>{authLabel}</p>
      </section>

      <section className="smj-SnapshotPanel__section">
        <div className="smj-SnapshotPanel__sectionHeader">
          <strong>Snapshot Behavior</strong>
          <button
            className="jp-mod-styled"
            type="button"
            onClick={() => {
              callbacks.onRefresh();
            }}
          >
            Refresh
          </button>
        </div>
        <label className="smj-SnapshotPanel__checkbox">
          <input
            type="checkbox"
            checked={viewState.metadata.all_cells_trigger}
            onChange={event => {
              callbacks.onToggleAllCells(event.target.checked);
            }}
          />
          Trigger on every executed cell
        </label>
        <label className="smj-SnapshotPanel__field">
          <span>Commit mode</span>
          <select
            className="jp-mod-styled"
            value={viewState.selectedCommitMode}
            onChange={event => {
              callbacks.onCommitModeChange(event.target.value as CommitMode);
            }}
          >
            <option value="prompt">Prompt</option>
            <option value="always">Always commit</option>
            <option value="never">Never commit</option>
          </select>
        </label>
        <label className="smj-SnapshotPanel__checkbox">
          <input
            type="checkbox"
            checked={viewState.rememberCommitChoice}
            onChange={event => {
              callbacks.onRememberCommitChoiceChange(event.target.checked);
            }}
          />
          Remember prompt decisions
        </label>
      </section>

      <section className="smj-SnapshotPanel__section">
        <strong>Watched Paths</strong>
        <div className="smj-SnapshotPanel__inlineForm">
          <input
            className="jp-mod-styled"
            type="text"
            value={watchPathInput}
            placeholder="relative/path/to/watch"
            onChange={event => {
              setWatchPathInput(event.target.value);
            }}
          />
          <button
            className="jp-mod-styled"
            type="button"
            onClick={() => {
              callbacks.onWatchPathSubmit(watchPathInput);
              setWatchPathInput("");
            }}
          >
            Add
          </button>
        </div>
        <ul className="smj-SnapshotPanel__list">
          {viewState.metadata.watched_paths.map(path => (
            <li key={path}>
              <code>{path}</code>
              <button
                className="jp-mod-styled"
                type="button"
                onClick={() => {
                  callbacks.onRemoveWatchedPath(path);
                }}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
        <p className="smj-SnapshotPanel__hint">
          Effective watched paths: {watchedPathSummary.join(", ") || "(none)"}
        </p>
      </section>

      <section className="smj-SnapshotPanel__section">
        <strong>Metadata</strong>
        <label className="smj-SnapshotPanel__field">
          <span>Tags</span>
          <input
            className="jp-mod-styled"
            type="text"
            value={tagsValue}
            placeholder="baseline, experiment-1"
            onChange={event => {
              callbacks.onTagsChange(event.target.value);
            }}
          />
        </label>
        <label className="smj-SnapshotPanel__field">
          <span>Run label</span>
          <input
            className="jp-mod-styled"
            type="text"
            value={viewState.userMetadata.run_label ?? ""}
            onChange={event => {
              callbacks.onRunLabelChange(event.target.value);
            }}
          />
        </label>
        <label className="smj-SnapshotPanel__field">
          <span>Experiment context</span>
          <input
            className="jp-mod-styled"
            type="text"
            value={viewState.userMetadata.experiment_context ?? ""}
            onChange={event => {
              callbacks.onExperimentContextChange(event.target.value);
            }}
          />
        </label>
        <label className="smj-SnapshotPanel__field">
          <span>Notes</span>
          <textarea
            className="jp-mod-styled"
            value={viewState.userMetadata.notes ?? ""}
            onChange={event => {
              callbacks.onNotesChange(event.target.value);
            }}
          />
        </label>
      </section>

      <section className="smj-SnapshotPanel__section">
        <strong>Context</strong>
        <p>
          Repo config loaded: {viewState.effectiveState?.repoConfigLoaded ? "yes" : "no"}
        </p>
        <p>
          Path rule: {viewState.effectiveState?.pathRule?.name ?? "(none)"}
        </p>
        <p>
          Git: {viewState.effectiveState?.repo?.repoRoot ?? "(no repository detected)"}
        </p>
      </section>

      <div className="smj-SnapshotPanel__actions">
        <button
          className="jp-mod-styled jp-mod-accept"
          type="button"
          disabled={!snapshotAvailability.enabled}
          onClick={() => {
            callbacks.onSnapshot();
          }}
        >
          Snapshot Now
        </button>
      </div>
      <p className="smj-SnapshotPanel__hint">{snapshotAvailability.message}</p>

      {viewState.statusMessage !== null ? (
        <p
          aria-live="polite"
          className={statusClassName ?? "smj-SnapshotPanel__status"}
          role="status"
        >
          {viewState.statusMessage}
        </p>
      ) : null}
    </section>
  );
}

export class SnapshotPanel extends ReactWidget {
  private viewState: SnapshotPanelViewState;

  constructor(private readonly callbacks: SnapshotPanelCallbacks) {
    super();
    this.viewState = {
      auth: {
        pendingRequestId: null,
        status: "unauthenticated",
        userEmail: null
      },
      effectiveState: null,
      isBusy: false,
      metadata: {
        all_cells_trigger: false,
        default_metadata: {},
        enabled: true,
        labarchives_target_notebook: null,
        labarchives_target_root_path: null,
        trigger_cell_ids: [],
        watched_paths: []
      },
      notebookPath: null,
      rememberCommitChoice: false,
      selectedCommitMode: "prompt",
      statusKind: null,
      statusMessage: null,
      userMetadata: {
        experiment_context: null,
        extra_fields: {},
        notes: null,
        run_label: null,
        tags: []
      }
    };
    this.addClass("smj-SnapshotPanel");
  }

  setViewState(viewState: SnapshotPanelViewState): void {
    this.viewState = viewState;
    this.update();
  }

  render(): React.JSX.Element {
    return (
      <SnapshotPanelBody callbacks={this.callbacks} viewState={this.viewState} />
    );
  }
}
