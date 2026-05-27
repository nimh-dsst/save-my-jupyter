# Usage

## Before You Start

Make sure the Jupyter server environment has:

- Python `3.12+`
- JupyterLab `4.x` or Notebook `7.x`
- the `save-my-jupyter` package installed, which also installs `labapi`

The notebook kernel does not need to install this package.

## Verify Installation

If you installed from a wheel or from source and want to confirm the extension
is visible to Jupyter:

```bash
python -m jupyter server extension list
```

The package registers its server extension automatically during installation.

## Open The UI

After installation:

1. Start JupyterLab or Notebook 7.
2. Open a notebook.
3. Open the command palette.
4. Run `Open Snapshot Settings`.

The extension adds:

- a right-side `Save My Jupyter` panel
- a `Snapshot` toolbar button on notebook panels
- command palette commands for snapshot and trigger-cell actions

## Authenticate With LabArchives

In the side panel:

1. Click `Connect`.
2. Complete the LabArchives sign-in flow in the new browser tab.
3. Return to JupyterLab.
4. Click `Refresh` if the panel does not update automatically.

The panel shows one of:

- `Not authenticated`
- `Authentication pending`
- `Authenticated as <email>`

If the browser finishes the callback but the panel still shows `Authentication
pending`, click `Refresh`.

## What Gets Uploaded

Every snapshot uploads the **full notebook file**, including:

- all cell outputs (`stdout`, `stderr`, rendered data, tracebacks)
- inline figures and embedded base64 image data
- whatever is currently visible in the notebook document

If a cell printed credentials, debug payloads, or anything else you would not
share with LabArchives, clear those outputs **before** triggering the snapshot.
There is no per-output redaction step today.

Watched files are also uploaded as separate attachments. The extension drops
common sensitive filenames (`.env`, `*.pem`, `*.key`, `id_rsa*`, `.netrc`,
files under `.ssh`/`.aws`, virtualenvs, and cache directories), but you should
still review your watched-paths list.

Upload guardrails stop oversized inline saves before they are sent to
LabArchives: notebooks are limited to 50 MiB, watched-file attachments are
limited to 25 MiB each, and raw diff attachments are truncated at 1 MiB. Rich
notebook diffs are still rendered separately when available. Figure outputs are
rendered inside the readable notebook or notebook-diff page rather than as
separate figure pages when the notebook is saved.

## Configure Snapshot Behavior

### Commit mode

Choose one of:

- `Prompt`
- `Always commit`
- `Never commit`

If commit mode is `Prompt`, the extension asks whether to create a Git commit
before the snapshot. If you enable `Remember prompt decisions`, the next choice
becomes the default commit mode.

### Trigger mode

You can either:

- mark specific cells as triggers
- enable `Trigger on every executed cell`

Use command palette commands:

- `Mark Cell As Trigger`
- `Unmark Cell As Trigger`
- `Toggle All Cells As Triggers`

Trigger state is stored in notebook metadata, so it travels with the notebook
file.

### Watched paths

Add watched paths in the side panel using relative paths such as:

- `outputs`
- `reports/result.csv`
- `artifacts/figures`

Rules:

- paths must be relative
- paths cannot escape the repo or notebook root
- file and directory-subtree watches are both supported

Watched paths are **not polled**. They are resolved and attached at snapshot
time — when you trigger a manual or trigger-cell snapshot, the backend matches
the configured globs against the current working tree and bundles the matching
files into the snapshot.

### Metadata

Each snapshot can include:

- tags stored as snapshot metadata text
- run label
- notes

These are sent with both manual and automatic snapshots.

Tags are not native LabArchives tag fields. They are written into the snapshot
metadata entry for search and review. For opt-in metadata extraction, add a
`tagme` key to notebook default metadata or snapshot extra fields with a
comma-, semicolon-, or newline-separated tag list; those values are merged into
the snapshot tags.

## Create Snapshots

### Manual snapshots

Use either:

- the notebook toolbar `Snapshot` button
- the command palette `Snapshot Now`
- the `Snapshot now` button in the side panel

Manual snapshots always enqueue a new snapshot request.

During a save, the side panel shows that snapshot artifacts are being prepared
and uploaded. After the save completes, the status includes the job ID, snapshot
ID, commit hash or URL when available, and the LabArchives page name or ID when
available.

### Trigger-cell snapshots

Trigger-cell snapshots happen when:

- a marked trigger cell finishes executing successfully, or
- all-cell mode is enabled and any cell finishes executing successfully

The backend deduplicates automatic snapshots so multiple trigger hits in one
logical run produce at most one snapshot.

Trigger-cell snapshots also emit JupyterLab notifications, so activity is
visible even when the Save My Jupyter side panel is closed.

### Watched-path attachments

There is no automatic "watched-path snapshot" trigger. Configured watched paths
are resolved at snapshot time (manual or trigger-cell) and the matching files
are uploaded as attachments alongside the notebook. The watch registration the
UI syncs to the server is what drives this matching.

If you need a snapshot to fire when a file changes, run the cell that produced
the file as a trigger cell, or invoke `Snapshot Now` manually.

## What Gets Stored

Each snapshot becomes one LabArchives page and may include:

- notebook summary information
- snapshot metadata
- Git metadata
- rich notebook diff text and a filtered raw patch for non-notebook files
- the notebook file, with visible output figures rendered inline in the
  readable notebook page
- watched file attachments
- execution summaries for text, image-only, multi-output, and error outputs

## Git Behavior

If the notebook is in a Git repository:

- the extension resolves repo root, remote, commit hash, and dirty state
- snapshot commits only stage the notebook and optionally watched paths
- unrelated modified files are not staged automatically
- LabArchives metadata distinguishes a new snapshot commit from an existing
  `HEAD` hash reused because no snapshot paths changed

If the notebook is not in a Git repository:

- snapshotting still works
- Git fields are left empty
- no commit/diff behavior is attempted

If the user declines commit:

- the snapshot still succeeds
- the working-tree diff against `HEAD` is stored

Dirty diffs are scoped to the notebook and configured watched paths. The rich
notebook diff omits raw notebook JSON noise; raw patch attachments omit notebook
JSON and image patches when a rich notebook diff can represent those changes.

## Shared Repo Workflow

If the repository has a `.save-my-jupyter.toml` file, the extension can:

- apply default watched paths
- define a default LabArchives notebook and root path
- define commit defaults
- define Git staging behavior

The side panel shows the resolved config for the current notebook so you can
see the actual values the backend will use.

If one notebook needs a different LabArchives destination than the repo
default, set notebook metadata overrides instead of adding repo path-matching
rules.

See [configuration.md](configuration.md) for the full format.

## Typical Shared-Repo Workflow

1. Commit a repo-level `.save-my-jupyter.toml`.
2. Open a notebook in that repository.
3. Confirm the side panel shows the resolved config and repo info.
4. Add notebook-specific overrides only where needed.
5. Use manual snapshots for explicit checkpoints and trigger cells for automatic
   capture during long-running analyses.

## Troubleshooting

### `ModuleNotFoundError: No module named 'labapi'`

Reinstall `save-my-jupyter` in the same Python environment that starts Jupyter.
`labapi` is a required dependency, so a missing import usually means the
package was installed into a different environment or the install was
incomplete.

### Snapshot rejected as duplicate

Automatic snapshots are deduplicated by run fingerprint. If you need another
snapshot immediately, use a manual snapshot.

### Watched path rejected

The path is probably:

- absolute
- using `..` to escape the root
- malformed after normalization

Use a relative path under the repo or notebook directory.

For more operational issues, use [troubleshooting.md](troubleshooting.md).
