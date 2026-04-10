# Usage

## Before You Start

Make sure the Jupyter server environment has:

- Python `3.12+`
- JupyterLab `4.x` or Notebook `7.x`
- the `save-my-jupyter` package installed
- `labapi` importable, or a local checkout of `labarchives-api` at one of:
  - `~/projects/labarchives-api/src`
  - `~/Downloads/labarchives-api/src`

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

Watched-path change detection currently uses backend polling. It is not instant,
but it does not require kernel-side code.

### Metadata

Each snapshot can include:

- tags
- run label
- experiment context
- notes

These are sent with both manual and automatic snapshots.

## Create Snapshots

### Manual snapshots

Use either:

- the notebook toolbar `Snapshot` button
- the command palette `Snapshot Now`
- the `Snapshot Now` button in the side panel

Manual snapshots always enqueue a new snapshot request.

### Trigger-cell snapshots

Trigger-cell snapshots happen when:

- a marked trigger cell finishes executing successfully, or
- all-cell mode is enabled and any cell finishes executing successfully

The backend deduplicates automatic snapshots so multiple trigger hits in one
logical run produce at most one snapshot.

### Watched-path snapshots

Watched-path snapshots happen when a configured watched path is:

- created
- modified
- deleted

The backend polls watched paths and emits a snapshot request when matching file
events occur. Automatic watched-path snapshots use the current notebook's
effective config and the watch registration most recently synced from the UI.

## What Gets Stored

Each snapshot becomes one LabArchives page and may include:

- notebook summary information
- snapshot metadata
- Git metadata
- a diff attachment or diff text when no commit is created
- the notebook file
- PNG figures found in visible notebook outputs
- watched file attachments
- a text/plain execution summary from notebook outputs when available

## Git Behavior

If the notebook is in a Git repository:

- the extension resolves repo root, remote, commit hash, and dirty state
- snapshot commits only stage the notebook and optionally watched paths
- unrelated modified files are not staged automatically

If the notebook is not in a Git repository:

- snapshotting still works
- Git fields are left empty
- no commit/diff behavior is attempted

If the user declines commit:

- the snapshot still succeeds
- the working-tree diff against `HEAD` is stored

## Shared Repo Workflow

If the repository has a `.save-my-jupyter.toml` file, the extension can:

- apply default watched paths
- route different notebook subpaths to different LabArchives destinations
- define commit defaults
- apply metadata templates

This is the recommended mode for teams sharing one repository.

See [configuration.md](configuration.md) for the full format.

## Typical Shared-Repo Workflow

1. Commit a repo-level `.save-my-jupyter.toml`.
2. Add one `path_rule` per major notebook area.
3. Open a notebook that lives under one of those paths.
4. Confirm the side panel shows the resolved path rule and repo info.
5. Add any notebook-specific overrides only where needed.
6. Use manual snapshots for explicit checkpoints and trigger cells for automatic
   capture during long-running analyses.

## Troubleshooting

### `labapi is not installed`

Make sure one of these is true:

- `labapi` is installed in the Jupyter server environment
- `~/projects/labarchives-api/src` exists
- `~/Downloads/labarchives-api/src` exists

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
