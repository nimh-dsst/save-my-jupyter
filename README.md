# Save My Jupyter

`save-my-jupyter` is a JupyterLab 4 / Notebook 7 extension for capturing
notebook development snapshots and persisting them to LabArchives.

It combines:

- a Jupyter Server extension for snapshot orchestration, Git integration,
  watched-path polling, LabArchives auth, and persistence
- a JupyterLab frontend extension for notebook UI, trigger-cell controls,
  watched-path editing, commit prompts, and snapshot metadata entry

## What It Does

Each snapshot can include:

- the saved notebook file
- Git context, including a commit hash or a diff against `HEAD`
- watched files that changed during the run
- visible notebook output summaries and PNG figures already present in the
  notebook document
- user-entered tags, notes, run labels, and opt-in metadata fields

Snapshots can be created by:

- clicking `Snapshot Now`
- executing a marked trigger cell
- enabling `Trigger on every executed cell`

Watched paths are not a snapshot trigger today — they are file globs that get
resolved and attached when a snapshot fires through one of the above sources.

Each snapshot becomes one LabArchives page.

## Compatibility

- Server environment: Python `>=3.12`
- Jupyter targets: JupyterLab `4.x`, Notebook `7.x`, Jupyter Server `2.x`
- Kernel policy: core snapshot behavior is kernel-independent

The extension runs in the Jupyter server environment. Notebook kernels do not
need the package installed.

## Install

### Install a built package

```bash
pip install dist/save_my_jupyter-0.1.0-py3-none-any.whl
```

The wheel bundles:

- automatic Jupyter Server extension registration
- the prebuilt labextension
- uninstall metadata in [`install.json`](install.json)

### Install from source for local use

```bash
npm ci
npm run build
pip install .
```

### Install from source for development

```bash
npm ci
uv sync --group dev
```

Editable installs call:

```bash
python -m jupyterlab.labextensions develop . --overwrite
```

Use a Python environment that already has JupyterLab available when relying on
editable frontend wiring.

## Quick Start

1. Start JupyterLab or Notebook 7 from the server environment where
   `save-my-jupyter` is installed.
2. Open a notebook.
3. Run `Open Snapshot Settings` from the command palette to open the `Save My
Jupyter` side panel.
4. Click `Connect` and finish the LabArchives sign-in flow.
5. Choose a commit mode and optional watched paths.
6. Mark trigger cells or enable `Trigger on every executed cell`.
7. Add tags, notes, or a run label.
8. Click `Snapshot Now` or run a trigger cell.

## Shared Repo Config

If the repository contains `.save-my-jupyter.toml`, the extension can:

- route different notebook subtrees to different LabArchives destinations
- apply shared watched-path defaults
- define repo-wide commit defaults
- attach metadata templates for path-specific work

This is the intended setup for teams sharing one repository.

## LabArchives Dependency

`labapi` is a required package dependency for the backend. Installing
`save-my-jupyter` into the Jupyter server environment should install it
automatically.

If you see `ModuleNotFoundError: No module named 'labapi'`, the package was
installed into a different Python environment or the install did not complete
successfully.

## Documentation

- [Usage guide](docs/usage.md)
- [Configuration reference](docs/configuration.md)
- [Development guide](docs/development.md)
- [Troubleshooting guide](docs/troubleshooting.md)
- [Architecture plan](plan.md)
- [Implementation checklist](checklist.md)

## Current Status

Implemented:

- typed backend request/config parsing
- shared `.save-my-jupyter.toml` repo config
- manual snapshots
- trigger-cell snapshots
- watched files attached at snapshot time
- Git commit/diff capture
- LabArchives auth flow and adapter
- strict Python and TypeScript lint/type/test gates

Current limitations:

- runtime state is in-memory only
- no retry queue for failed LabArchives writes
- watched paths are matched at snapshot time only; they are not polled and do
  not fire snapshots on file changes
- artifact capture is intentionally kernel-independent, so it only uses notebook
  document state and watched files
- richer kernel-specific enrichment is not implemented yet

## Quality Gates

Python checks use:

- `ruff`
- `ty`
- `pytest`

Frontend checks use:

- `eslint`
- `tsc --noEmit`
- frontend unit tests

## Further Reading

For the full user workflow, use [docs/usage.md](docs/usage.md). For the shared
repo config format, use [docs/configuration.md](docs/configuration.md).
