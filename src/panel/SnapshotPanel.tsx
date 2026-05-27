import { ReactWidget } from "@jupyterlab/apputils";
import * as React from "react";

import {
  NO_NOTEBOOK_CONFIG_MESSAGE,
  REPO_CONFIG_FILENAME,
  starterConfigButtonLabel,
  starterConfigCreateAvailable,
  type StarterConfigInspection,
  type StarterConfigResult,
} from "../config/starterConfig";
import {
  activeCellTriggerDescription,
  triggerCommandLabels,
  triggerModeDescription,
  triggerToggleLabel,
} from "../notebook/triggers";
import type { WatchedPathAddResult } from "../notebook/watchedPaths";
import type { ReadableSignal } from "../signals";

import {
  getSnapshotBlockedMessage,
  isSnapshotActionEnabled,
  type PanelState,
  type SnapshotOptionsState,
  type TargetOptionsState,
} from "./controller";

const { useEffect, useState } = React;

function useSignal<T>(signal: ReadableSignal<T>): T {
  const [value, setValue] = useState<T>(signal.get());
  useEffect(
    () =>
      signal.subscribe(() => {
        setValue(signal.get());
      }),
    [signal],
  );
  return value;
}

export interface SnapshotPanelProps {
  readonly state: ReadableSignal<PanelState>;
  readonly onConnect: () => void;
  readonly onRefresh: () => void;
  readonly onSnapshot: () => void;
  readonly onCheckConfig: () => Promise<StarterConfigInspection>;
  readonly onEnsureConfig: () => Promise<StarterConfigResult>;
  readonly onAddWatchedPath: (path: string) => WatchedPathAddResult;
  readonly onRemoveWatchedPath: (path: string) => void;
  readonly onToggleAllCellsTrigger: () => void;
  readonly onToggleCellTrigger: () => void;
  readonly onSnapshotOptionsChange: (
    patch: Partial<
      Pick<
        SnapshotOptionsState,
        | "commitMode"
        | "commitDecision"
        | "rememberCommitChoice"
        | "runLabel"
        | "tags"
        | "notes"
        | "metadataFields"
      >
    >,
  ) => void;
  readonly onTargetOptionsChange: (
    patch: Partial<Omit<TargetOptionsState, "availableNotebookNames">>,
  ) => void;
}

interface LocalStatus {
  readonly kind: "info" | "success" | "warning" | "error";
  readonly message: string;
}

export function SnapshotPanelComponent(
  props: SnapshotPanelProps,
): React.JSX.Element {
  const { onCheckConfig, onEnsureConfig } = props;
  const state = useSignal(props.state);
  const [configExists, setConfigExists] = useState<boolean | null>(null);
  const [configBusy, setConfigBusy] = useState(false);
  const [configStatus, setConfigStatus] = useState<LocalStatus | null>(null);
  const [watchedPathInput, setWatchedPathInput] = useState("");
  const [watchedPathStatus, setWatchedPathStatus] =
    useState<LocalStatus | null>(null);
  const canCreateConfig = starterConfigCreateAvailable(configExists);
  const hasNotebook = state.notebookName !== null;
  const artifactCount = state.willBeSaved?.artifacts.length ?? 0;
  const snapshotBlockedMessage = getSnapshotBlockedMessage(state);

  useEffect(() => {
    let cancelled = false;
    setConfigExists(null);
    setConfigStatus(null);
    if (!hasNotebook) {
      return () => {
        cancelled = true;
      };
    }
    onCheckConfig()
      .then((inspection) => {
        if (!cancelled) {
          setConfigExists(inspection.exists);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setConfigStatus({
            kind: "warning",
            message: "Unable to check config status.",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [hasNotebook, onCheckConfig, state.notebookName]);

  useEffect(() => {
    setWatchedPathInput("");
    setWatchedPathStatus(null);
  }, [state.notebookName]);

  const ensureConfig = (): void => {
    if (state.notebookName === null) {
      setConfigStatus({
        kind: "warning",
        message: NO_NOTEBOOK_CONFIG_MESSAGE,
      });
      return;
    }
    setConfigBusy(true);
    onEnsureConfig()
      .then((result) => {
        setConfigExists(true);
        setConfigStatus({
          kind: result.status === "created" ? "success" : "info",
          message: result.message,
        });
      })
      .catch(() => {
        setConfigStatus({
          kind: "error",
          message: "Unable to create the starter config.",
        });
      })
      .finally(() => {
        setConfigBusy(false);
      });
  };

  const addWatchedPath = (event: React.FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    const result = props.onAddWatchedPath(watchedPathInput);
    if (!result.ok) {
      setWatchedPathStatus({ kind: "warning", message: result.message });
      return;
    }
    setWatchedPathInput("");
    setWatchedPathStatus({
      kind: "success",
      message: `Watching ${result.path}.`,
    });
  };

  const removeWatchedPath = (path: string): void => {
    props.onRemoveWatchedPath(path);
    setWatchedPathStatus({
      kind: "info",
      message: `Stopped watching ${path}.`,
    });
  };

  return (
    <div className="smj-Panel">
      <header className="smj-PanelHeader">
        <h2>Save My Jupyter</h2>
        <p>{state.notebookName ?? "Open a notebook to enable snapshots."}</p>
      </header>
      <section className="smj-Snapshot">
        <div className="smj-SectionTitleRow">
          <h3>Snapshot</h3>
          <span
            className={`smj-Badge ${
              state.readiness.canSnapshot
                ? "smj-Badge-success"
                : "smj-Badge-warning"
            }`}
          >
            {state.readiness.canSnapshot ? "Ready" : "Needs setup"}
          </span>
        </div>
        <div className="smj-ActionStack">
          <button
            className="smj-PrimaryButton"
            type="button"
            disabled={!isSnapshotActionEnabled(state)}
            onClick={props.onSnapshot}
          >
            Snapshot now
          </button>
          <button type="button" disabled={state.busy} onClick={props.onRefresh}>
            Refresh
          </button>
        </div>
        <p className="smj-OutputDisclosure" role="note">
          Snapshots upload the full notebook with outputs, including stdout,
          stderr, rendered data, and embedded figures. Clear sensitive outputs
          before saving.
        </p>
        {snapshotBlockedMessage !== null && (
          <p className="smj-Blocked">{snapshotBlockedMessage}</p>
        )}
        <div role="status" aria-live="polite">
          {state.status !== null && (
            <p className={`smj-Status smj-Status-${state.status.kind}`}>
              {state.status.message}
            </p>
          )}
        </div>
      </section>
      <section className="smj-WillBeSaved">
        <div className="smj-SectionTitleRow">
          <h3>What will be saved</h3>
          <span className="smj-Badge">
            {artifactCount === 1 ? "1 item" : `${String(artifactCount)} items`}
          </span>
        </div>
        {state.willBeSaved === null ? (
          <p>Snapshot review unavailable.</p>
        ) : (
          <>
            <div className="smj-Subsection">
              <h4>Destination</h4>
              <dl className="smj-Facts">
                <div>
                  <dt>Notebook</dt>
                  <dd>{state.willBeSaved.destination.notebookLabel}</dd>
                </div>
                <div>
                  <dt>Path</dt>
                  <dd>{state.willBeSaved.destination.rootLabel}</dd>
                </div>
              </dl>
            </div>
            <div className="smj-Subsection">
              <h4>Metadata</h4>
              <dl className="smj-Facts">
                {state.willBeSaved.metadataRows.map((row) => (
                  <div key={row.label}>
                    <dt>{row.label}</dt>
                    <dd>{row.value}</dd>
                  </div>
                ))}
              </dl>
            </div>
            {state.willBeSaved.policyRows.length > 0 && (
              <div className="smj-Subsection">
                <h4>Policy</h4>
                <dl className="smj-Facts">
                  {state.willBeSaved.policyRows.map((row) => (
                    <div key={row.label}>
                      <dt>{row.label}</dt>
                      <dd>{row.value}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}
            <div className="smj-Subsection">
              <h4>Repository</h4>
              <dl className="smj-Facts">
                {state.willBeSaved.repoRows.map((row) => (
                  <div key={row.label}>
                    <dt>{row.label}</dt>
                    <dd>{row.value}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <div className="smj-Subsection">
              <h4>Captured items</h4>
              {state.willBeSaved.emptyMessage !== null ? (
                <p>{state.willBeSaved.emptyMessage}</p>
              ) : (
                <ul className="smj-ArtifactList">
                  {state.willBeSaved.artifacts.map((artifact, index) => (
                    <li key={`${artifact.kind}-${String(index)}`}>
                      <span className="smj-ArtifactKind">{artifact.kind}</span>
                      <span>{artifact.summary}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <p className="smj-MetaNote">{state.willBeSaved.freshness}</p>
          </>
        )}
      </section>
      <section className="smj-WatchedPaths">
        <div className="smj-SectionTitleRow">
          <h3>Watched files</h3>
          <span className="smj-Badge">
            {state.watchedPaths.length === 1
              ? "1 path"
              : `${String(state.watchedPaths.length)} paths`}
          </span>
        </div>
        <form className="smj-InlineForm" onSubmit={addWatchedPath}>
          <label className="smj-Field">
            <span>Path or glob</span>
            <input
              type="text"
              aria-label="Watched file path or glob"
              disabled={!hasNotebook}
              placeholder="outputs/result.csv"
              value={watchedPathInput}
              onChange={(event) => {
                setWatchedPathInput(event.currentTarget.value);
              }}
            />
          </label>
          <button
            type="submit"
            disabled={!hasNotebook}
          >
            Add
          </button>
        </form>
        {state.watchedPaths.length === 0 ? (
          <p>No watched files configured.</p>
        ) : (
          <ul className="smj-WatchedPathList">
            {state.watchedPaths.map((path) => (
              <li key={path}>
                <code>{path}</code>
                <button
                  type="button"
                  onClick={() => {
                    removeWatchedPath(path);
                  }}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
        {watchedPathStatus !== null && (
          <p
            className={`smj-Status smj-Status-${watchedPathStatus.kind}`}
            role="status"
            aria-live="polite"
          >
            {watchedPathStatus.message}
          </p>
        )}
      </section>
      <section className="smj-TriggerOptions">
        <div className="smj-SectionTitleRow">
          <h3>Triggers</h3>
          <span className="smj-Badge">
            {triggerModeDescription(state.triggerOptions.allCellsTrigger)}
          </span>
        </div>
        <dl className="smj-Facts">
          <div>
            <dt>Mode</dt>
            <dd>
              {triggerModeDescription(state.triggerOptions.allCellsTrigger)}
            </dd>
          </div>
          <div>
            <dt>Active cell</dt>
            <dd>
              {activeCellTriggerDescription(state.triggerOptions.activeCell)}
            </dd>
          </div>
        </dl>
        <div className="smj-ActionStack">
          <button
            type="button"
            disabled={state.triggerOptions.activeCell === "unknown"}
            onClick={props.onToggleCellTrigger}
          >
            {triggerToggleLabel(state.triggerOptions.activeCell)}
          </button>
          <button type="button" onClick={props.onToggleAllCellsTrigger}>
            {triggerCommandLabels.toggleAllCells}
          </button>
        </div>
      </section>
      <section className="smj-SnapshotOptions">
        <div className="smj-SectionTitleRow">
          <h3>Snapshot options</h3>
          <span className="smj-Badge">{state.snapshotOptions.commitMode}</span>
        </div>
        <div className="smj-Subsection">
          <h4>Commit</h4>
          <label className="smj-Field">
            <span>Default mode</span>
            <select
              value={state.snapshotOptions.commitMode}
              onChange={(event) => {
                props.onSnapshotOptionsChange({
                  commitMode: event.currentTarget
                    .value as SnapshotOptionsState["commitMode"],
                });
              }}
            >
              <option value="ask">Ask</option>
              <option value="always">Always commit</option>
              <option value="never">Never commit</option>
            </select>
          </label>
          {state.snapshotOptions.commitMode === "ask" && (
            <>
              <div className="smj-Segmented">
                <label>
                  <input
                    type="radio"
                    name="smj-commit-decision"
                    checked={state.snapshotOptions.commitDecision === "always"}
                    onChange={() => {
                      props.onSnapshotOptionsChange({ commitDecision: "always" });
                    }}
                  />
                  <span>Commit this snapshot</span>
                </label>
                <label>
                  <input
                    type="radio"
                    name="smj-commit-decision"
                    checked={state.snapshotOptions.commitDecision === "never"}
                    onChange={() => {
                      props.onSnapshotOptionsChange({ commitDecision: "never" });
                    }}
                  />
                  <span>Reuse HEAD</span>
                </label>
              </div>
              <label className="smj-Checkbox">
                <input
                  type="checkbox"
                  checked={state.snapshotOptions.rememberCommitChoice}
                  onChange={(event) => {
                    props.onSnapshotOptionsChange({
                      rememberCommitChoice: event.currentTarget.checked,
                    });
                  }}
                />
                <span>Remember this decision</span>
              </label>
            </>
          )}
        </div>
        <div className="smj-Subsection">
          <h4>LabArchives target</h4>
          <label className="smj-Field">
            <span>Notebook</span>
            <input
              type="text"
              list="smj-target-notebooks"
              value={state.targetOptions.notebookName}
              placeholder={state.willBeSaved?.destination.notebookName ?? ""}
              onChange={(event) => {
                props.onTargetOptionsChange({
                  notebookName: event.currentTarget.value,
                });
              }}
            />
            <datalist id="smj-target-notebooks">
              {state.targetOptions.availableNotebookNames.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          </label>
          <label className="smj-Field">
            <span>Root path</span>
            <input
              type="text"
              value={state.targetOptions.rootPath}
              placeholder={state.willBeSaved?.destination.rootPath ?? ""}
              onChange={(event) => {
                props.onTargetOptionsChange({
                  rootPath: event.currentTarget.value,
                });
              }}
            />
          </label>
        </div>
        <div className="smj-Subsection">
          <h4>Metadata</h4>
          <label className="smj-Field">
            <span>Run label</span>
            <input
              type="text"
              value={state.snapshotOptions.runLabel}
              onChange={(event) => {
                props.onSnapshotOptionsChange({
                  runLabel: event.currentTarget.value,
                });
              }}
            />
          </label>
          <label className="smj-Field">
            <span>Tags</span>
            <input
              type="text"
              value={state.snapshotOptions.tags}
              placeholder="baseline, gpu"
              onChange={(event) => {
                props.onSnapshotOptionsChange({
                  tags: event.currentTarget.value,
                });
              }}
            />
          </label>
          <label className="smj-Field">
            <span>Notes</span>
            <textarea
              value={state.snapshotOptions.notes}
              onChange={(event) => {
                props.onSnapshotOptionsChange({
                  notes: event.currentTarget.value,
                });
              }}
            />
          </label>
          <label className="smj-Field">
            <span>Additional fields</span>
            <textarea
              value={state.snapshotOptions.metadataFields}
              onChange={(event) => {
                props.onSnapshotOptionsChange({
                  metadataFields: event.currentTarget.value,
                });
              }}
            />
          </label>
        </div>
      </section>
      <section className="smj-Readiness smj-Setup">
        <div className="smj-SectionTitleRow">
          <h3>Connection & config</h3>
          <span
            className={`smj-Badge ${
              state.readiness.canSnapshot
                ? "smj-Badge-success"
                : "smj-Badge-warning"
            }`}
          >
            {state.readiness.canSnapshot ? "Connected" : "Not connected"}
          </span>
        </div>
        <div className="smj-Subsection">
          <h4>LabArchives</h4>
          <div className="smj-SetupRow">
            <p>{state.readiness.authDescription}</p>
            <button
              type="button"
              disabled={state.authBusy}
              onClick={props.onConnect}
            >
              {state.readiness.authButtonLabel}
            </button>
          </div>
          {state.readiness.blockedMessage !== null && (
            <p className="smj-Blocked">{state.readiness.blockedMessage}</p>
          )}
        </div>
        <div className="smj-Subsection">
          <h4>Workspace config</h4>
          <div className="smj-SetupRow">
            {state.notebookName !== null && canCreateConfig && (
              <button
                type="button"
                disabled={configBusy}
                onClick={ensureConfig}
              >
                {starterConfigButtonLabel(configExists)}
              </button>
            )}
            {state.notebookName === null ? (
              <p className="smj-Blocked">{NO_NOTEBOOK_CONFIG_MESSAGE}</p>
            ) : configExists === true ? (
              <p>This config is already available for the current notebook.</p>
            ) : configExists === null ? (
              <p>Checking for an existing config.</p>
            ) : (
              <p>
                Create a starter <code>{REPO_CONFIG_FILENAME}</code> to share
                defaults for this workspace.
              </p>
            )}
          </div>
        </div>
        {state.willBeSaved !== null && (
          <div className="smj-Subsection">
            <h4>Repository</h4>
            <dl className="smj-Facts">
              {state.willBeSaved.repoRows.map((row) => (
                <div key={row.label}>
                  <dt>{row.label}</dt>
                  <dd>{row.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
        {configStatus !== null && (
          <p
            className={`smj-Status smj-Status-${configStatus.kind}`}
            role="status"
            aria-live="polite"
          >
            {configStatus.message}
          </p>
        )}
      </section>
      <section className="smj-Activity">
        <div className="smj-SectionTitleRow">
          <h3>Activity</h3>
          <span className="smj-Badge">
            {state.activity.totalRows === 1
              ? "1 run"
              : `${String(state.activity.totalRows)} runs`}
          </span>
        </div>
        {state.activity.emptyMessage !== null ? (
          <p>{state.activity.emptyMessage}</p>
        ) : (
          <>
            {state.activity.overflowMessage !== null && (
              <p className="smj-MetaNote">{state.activity.overflowMessage}</p>
            )}
            <ul className="smj-ActivityList">
              {state.activity.rows.map((row) => (
                <li
                  key={row.jobId}
                  className={row.isError ? "smj-Error" : undefined}
                >
                  <strong>{row.statusLabel}</strong> {row.message}
                  {row.runOutcomeLabel !== null && (
                    <>
                      {" "}
                      <span className="smj-RunOutcome">
                        {row.runOutcomeLabel}
                      </span>
                    </>
                  )}
                {row.url !== null && (
                  <>
                    {" "}
                    <a href={row.url} target="_blank" rel="noreferrer">
                      Open in LabArchives
                    </a>
                  </>
                )}
                {row.phaseItems.length > 0 && (
                  <ol className="smj-PhaseList">
                    {row.phaseItems.map((phase) => (
                      <li
                        key={phase.label}
                        className={`smj-Phase-${phase.status}`}
                      >
                        <span>{phase.label}</span>
                        <span>{phase.status}</span>
                      </li>
                    ))}
                  </ol>
                )}
              </li>
            ))}
            </ul>
          </>
        )}
      </section>
    </div>
  );
}

export class SnapshotPanel extends ReactWidget {
  constructor(private readonly props: SnapshotPanelProps) {
    super();
    this.addClass("smj-PanelWidget");
    this.id = "save-my-jupyter-panel";
    this.title.label = "Save My Jupyter";
    this.title.closable = false;
  }

  protected render(): React.JSX.Element {
    return <SnapshotPanelComponent {...this.props} />;
  }
}
