import { ReactWidget } from "@jupyterlab/apputils";
import * as React from "react";

import type { ReadableSignal } from "../signals";

import type { PanelState } from "./controller";

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
  readonly onSnapshot: () => void;
}

export function SnapshotPanelComponent(props: SnapshotPanelProps): React.JSX.Element {
  const state = useSignal(props.state);
  return (
    <div className="smj-Panel">
      <h2>Save My Jupyter</h2>
      <section className="smj-Readiness">
        <h3>Readiness</h3>
        <p>{state.readiness.authDescription}</p>
        <button type="button" onClick={props.onConnect}>
          {state.readiness.authButtonLabel}
        </button>
        {state.readiness.blockedMessage !== null && (
          <p className="smj-Blocked">{state.readiness.blockedMessage}</p>
        )}
      </section>
      <section className="smj-Snapshot">
        <h3>Snapshot</h3>
        <p>
          Notebook:{" "}
          {state.notebookName ?? "Open a notebook to enable snapshots."}
        </p>
        <button
          type="button"
          disabled={!state.readiness.canSnapshot || state.busy}
          onClick={props.onSnapshot}
        >
          Snapshot now
        </button>
        {state.status !== null && <p className="smj-Status">{state.status}</p>}
      </section>
      <section className="smj-Activity">
        <h3>Activity</h3>
        {state.activity.emptyMessage !== null ? (
          <p>{state.activity.emptyMessage}</p>
        ) : (
          <ul>
            {state.activity.rows.map((row) => (
              <li key={row.jobId} className={row.isError ? "smj-Error" : undefined}>
                <strong>{row.statusLabel}</strong> {row.message}
                {row.url !== null && (
                  <>
                    {" "}
                    <a href={row.url} target="_blank" rel="noreferrer">
                      Open in LabArchives
                    </a>
                  </>
                )}
              </li>
            ))}
          </ul>
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
    this.title.closable = true;
  }

  protected render(): React.JSX.Element {
    return <SnapshotPanelComponent {...this.props} />;
  }
}
