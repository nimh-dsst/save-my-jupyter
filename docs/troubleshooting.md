# Troubleshooting

## Extension Does Not Appear In JupyterLab Or Notebook 7

Check that the package is installed in the same Python environment that starts
Jupyter:

```bash
pip show save-my-jupyter
python -m jupyter server extension list
```

If the package is installed but the UI does not appear:

- restart JupyterLab or Notebook 7
- confirm the server environment is Python `3.10+`
- rebuild the frontend assets if you are working from source:

```bash
npm ci
npm run build
```

## Editable Install Fails

Editable installs use:

```bash
python -m jupyterlab.labextensions develop . --overwrite
```

If that fails, the Python environment probably does not have JupyterLab
available yet. Install JupyterLab into that environment first, then rerun:

```bash
uv sync --group dev
```

## `ModuleNotFoundError: No module named 'labapi'`

Install or reinstall `save-my-jupyter` in the same Python environment that
starts Jupyter. `labapi` is a required dependency, so this error usually means
the package was installed into a different environment or the install was
incomplete.

## LabArchives Auth Stays Pending

If the panel remains in `Authentication pending`:

- finish the LabArchives callback flow in the browser tab opened by `Connect`
- return to Jupyter and click `Refresh`
- verify the browser can reach the Jupyter server callback URL

If the callback fails, restart auth from the panel and try again.

## Manual Snapshot Fails Or Is Rejected

Common causes:

- no notebook is open
- LabArchives auth has not completed
- the notebook path in the request is invalid
- the repo config or notebook metadata contains invalid tracked paths

Automatic snapshots may also be rejected as duplicates if they land in the same
run fingerprint. Use `Snapshot Now` if you need a separate snapshot immediately.

## Tracked Path Is Rejected

Tracked paths must be:

- relative
- under the repo root, or under the notebook directory if no repo is detected
- free of `..` path escapes

Examples of valid tracked paths:

- `outputs`
- `reports/latest.csv`
- `artifacts/figures`

## Tracked-File Snapshot Did Not Fire

Tracked files are not a snapshot trigger. They are matched only when a manual
or trigger-cell snapshot runs. That means:

- file changes alone do not create snapshots
- only configured relative paths are attached
- run `Snapshot Now` or execute a trigger cell to capture the current files

Use the side panel `Refresh` action if you changed notebook metadata or repo
config and want to resync the current notebook state.

## Git Metadata Is Empty

Snapshots still work outside Git repos. In that case:

- repo fields are left empty
- no commit is created
- no diff against `HEAD` is generated

If you expected Git data, make sure the notebook lives inside a Git working
tree.

## Frontend Build Fails

For source builds, use:

```bash
npm ci
npm run build
```

The build relies on the local `jupyterlab_core` manifest committed in this repo.
If `node_modules` is stale or incomplete, rerun `npm ci`.
