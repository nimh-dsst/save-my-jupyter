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
- confirm the server environment is Python `3.12+`
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
pip install -e .[dev]
```

## `labapi` Cannot Be Imported

The backend tries:

1. `import labapi`
2. `~/projects/labarchives-api/src`
3. `~/Downloads/labarchives-api/src`

If snapshots fail with a `missing_labapi` error, make sure one of those paths is
available to the Jupyter server process.

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
- the repo config or notebook metadata contains invalid watched paths

Automatic snapshots may also be rejected as duplicates if they land in the same
run fingerprint. Use `Snapshot Now` if you need a separate snapshot immediately.

## Watched Path Is Rejected

Watched paths must be:

- relative
- under the repo root, or under the notebook directory if no repo is detected
- free of `..` path escapes

Examples of valid watched paths:

- `outputs`
- `reports/latest.csv`
- `artifacts/figures`

## Watched-Path Snapshot Did Not Fire

The current watcher implementation polls registered paths instead of using a
native OS file event backend. That means:

- changes are detected on the polling interval, not instantly
- the notebook must have synced its watched-path registration first
- only configured relative paths are tracked

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
