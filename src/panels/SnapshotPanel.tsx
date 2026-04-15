import { ReactWidget } from "@jupyterlab/apputils";
import React from "react";

import { getSnapshotAvailability } from "../panelBehavior";
import {
  createInitialViewState,
  type SnapshotPanelViewState,
  type StatusKind
} from "../panelState";
import type { CommitMode } from "../types";

export interface SnapshotPanelCallbacks {
  onAuthenticate(): void;
  onCommitModeChange(value: CommitMode): void;
  onGenerateRepoConfig(): void;
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

interface SetupActionRowProps {
  buttonDisabled?: boolean;
  buttonLabel: string;
  description: string;
  extraHint?: string;
  onClick: () => void;
  statusKind: StatusKind;
  statusMessage: string | null;
  testId: string;
  title: string;
}

function getStatusClassName(kind: StatusKind): string {
  return kind === null
    ? "smj-SnapshotPanel__status"
    : `smj-SnapshotPanel__status smj-SnapshotPanel__status--${kind}`;
}

function StatusMessage({
  kind,
  message
}: {
  kind: StatusKind;
  message: string | null;
}): React.JSX.Element | null {
  if (message === null) {
    return null;
  }

  return (
    <p
      aria-live="polite"
      className={getStatusClassName(kind)}
      role="status"
    >
      {message}
    </p>
  );
}

function SetupActionRow({
  buttonDisabled = false,
  buttonLabel,
  description,
  extraHint,
  onClick,
  statusKind,
  statusMessage,
  testId,
  title
}: SetupActionRowProps): React.JSX.Element {
  return (
    <div
      className="smj-SnapshotPanel__actionRow"
      data-smj-action={testId}
    >
      <div className="smj-SnapshotPanel__row">
        <div className="smj-SnapshotPanel__rowCopy">
          <strong className="smj-SnapshotPanel__rowTitle">{title}</strong>
          <p className="smj-SnapshotPanel__hint">{description}</p>
        </div>
        <button
          className="jp-mod-styled smj-SnapshotPanel__button"
          type="button"
          disabled={buttonDisabled}
          onClick={() => {
            onClick();
          }}
        >
          {buttonLabel}
        </button>
      </div>
      {extraHint === undefined ? null : (
        <p className="smj-SnapshotPanel__hint">{extraHint}</p>
      )}
      <StatusMessage
        kind={statusKind}
        message={statusMessage}
      />
    </div>
  );
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

  const authLabel =
    viewState.auth.status === "authenticated"
      ? `Authenticated as ${viewState.auth.userEmail ?? "unknown"}`
      : viewState.auth.status === "pending"
        ? "Authentication pending"
        : viewState.auth.storedUserEmail !== null
          ? `Not authenticated. Previously connected as ${viewState.auth.storedUserEmail}`
        : "Not authenticated";
  const selectedCellLabel = viewState.activeCellId ?? "No selected cell";
  const repoConfigPath =
    viewState.effectiveState?.repoConfigPath ?? "Open a notebook to choose a config location.";
  const repoConfigButtonLabel = viewState.effectiveState?.repoConfigLoaded
    ? "Ensure config exists"
    : "Create starter config";
  const pathRuleLabel = viewState.effectiveState?.pathRule?.name ?? "(none)";
  const gitLabel = viewState.effectiveState?.repo?.repoRoot ?? "(no repository detected)";
  const snapshotAvailability = getSnapshotAvailability(
    viewState.auth,
    viewState.notebookPath,
    viewState.isBusy
  );

  return (
    <>
      <div className="jp-SidePanel-header">
        <span className="smj-SnapshotPanel__headerTitle">Save My Jupyter</span>
      </div>
      <div className="jp-SidePanel-toolbar smj-SnapshotPanel__toolbar">
        <button
          className="jp-mod-styled jp-mod-accept smj-SnapshotPanel__toolbarButton"
          type="button"
          disabled={!snapshotAvailability.enabled}
          onClick={() => {
            callbacks.onSnapshot();
          }}
        >
          Snapshot now
        </button>
        <button
          className="jp-mod-styled smj-SnapshotPanel__toolbarButton"
          type="button"
          onClick={() => {
            callbacks.onRefresh();
          }}
        >
          Refresh
        </button>
      </div>
      <section className="jp-SidePanel-content smj-SnapshotPanel__content">
        <div className="smj-SnapshotPanel__body">
          <div className="smj-SnapshotPanel__summary">
            <span className="smj-SnapshotPanel__summaryLabel">Notebook</span>
            <p className="smj-SnapshotPanel__summaryPath">
              {viewState.notebookPath ?? "Open a notebook to configure snapshots."}
            </p>
            <dl className="smj-SnapshotPanel__summaryFacts">
              <div>
                <dt>Path rule</dt>
                <dd>{pathRuleLabel}</dd>
              </div>
              <div>
                <dt>Git</dt>
                <dd>{gitLabel}</dd>
              </div>
            </dl>
          </div>
          <p className="smj-SnapshotPanel__hint smj-SnapshotPanel__availability">
            {snapshotAvailability.message}
          </p>

          <section className="smj-SnapshotPanel__section">
            <h3 className="smj-SnapshotPanel__sectionTitle">Setup</h3>
            <SetupActionRow
              buttonLabel="Connect"
              description={authLabel}
              onClick={() => {
                callbacks.onAuthenticate();
              }}
              statusKind={viewState.authStatusKind}
              statusMessage={viewState.authStatusMessage}
              testId="auth"
              title="LabArchives"
            />
            <SetupActionRow
              buttonDisabled={viewState.notebookPath === null}
              buttonLabel={repoConfigButtonLabel}
              description={repoConfigPath}
              extraHint={
                viewState.effectiveState?.repoConfigLoaded
                  ? "This config is already available for the current notebook."
                  : "Create a starter .save-my-jupyter.toml to share defaults for this workspace."
              }
              onClick={() => {
                callbacks.onGenerateRepoConfig();
              }}
              statusKind={viewState.configStatusKind}
              statusMessage={viewState.configStatusMessage}
              testId="config"
              title="Project config"
            />
          </section>

          <section className="smj-SnapshotPanel__section">
            <h3 className="smj-SnapshotPanel__sectionTitle">Capture</h3>
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
                checked={viewState.metadata.all_cells_trigger}
                onChange={event => {
                  callbacks.onToggleAllCells(event.target.checked);
                }}
              />
              Trigger on every executed cell
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
            <div className="smj-SnapshotPanel__subsection">
              <h4 className="smj-SnapshotPanel__subsectionTitle">Trigger cells</h4>
            </div>
            <dl className="smj-SnapshotPanel__facts">
              <div>
                <dt>Selected cell</dt>
                <dd>{selectedCellLabel}</dd>
              </div>
              <div>
                <dt>Trigger state</dt>
                <dd>{viewState.activeCellIsTrigger ? "Marked" : "Not marked"}</dd>
              </div>
            </dl>
            <p className="smj-SnapshotPanel__hint">
              Use the cell action button to mark trigger cells. Trigger cells in this
              notebook:{" "}
              {viewState.metadata.trigger_cell_ids.join(", ") || "(none)"}
            </p>
            <div className="smj-SnapshotPanel__subsection">
              <h4 className="smj-SnapshotPanel__subsectionTitle">Watched paths</h4>
            </div>
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
                className="jp-mod-styled smj-SnapshotPanel__button"
                type="button"
                onClick={() => {
                  callbacks.onWatchPathSubmit(watchPathInput);
                  setWatchPathInput("");
                }}
              >
                Add
              </button>
            </div>
            {viewState.metadata.watched_paths.length === 0 ? (
              <p className="smj-SnapshotPanel__hint">No watched paths yet.</p>
            ) : (
              <ul className="smj-SnapshotPanel__list">
                {viewState.metadata.watched_paths.map(path => (
                  <li key={path}>
                    <code>{path}</code>
                    <button
                      className="jp-mod-styled smj-SnapshotPanel__button"
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
            )}
            <p className="smj-SnapshotPanel__hint">
              Effective: {watchedPathSummary.join(", ") || "(none)"}
            </p>
          </section>

          <section className="smj-SnapshotPanel__section">
            <h3 className="smj-SnapshotPanel__sectionTitle">Metadata</h3>
            <label className="smj-SnapshotPanel__field">
              <span>Tags</span>
              <input
                className="jp-mod-styled"
                type="text"
                value={viewState.tagsInput}
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

          <StatusMessage
            kind={viewState.statusKind}
            message={viewState.statusMessage}
          />
        </div>
      </section>
    </>
  );
}

export class SnapshotPanel extends ReactWidget {
  private viewState: SnapshotPanelViewState;

  constructor(private readonly callbacks: SnapshotPanelCallbacks) {
    super();
    this.viewState = createInitialViewState();
    this.addClass("jp-SidePanel");
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
