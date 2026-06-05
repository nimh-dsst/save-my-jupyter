# Configuration

## Overview

Configuration is merged from five layers, highest precedence first:

1. manual snapshot request overrides
2. notebook metadata
3. user settings
4. repo config in `.save-my-jupyter.toml`
5. inferred defaults

This lets a shared repository define stable defaults while still allowing
notebook-local and user-local overrides.

## Server LabArchives Settings

Set these in the Jupyter server process environment, or in a `.env` file at the
Jupyter server root. Process environment variables take precedence over `.env`
values.

- `ACCESS_KEYID`: LabArchives API access key id.
- `ACCESS_PWD`: LabArchives API access password.
- `API_URL`: optional LabArchives API URL; defaults to
  `https://api.labarchives.com`.
- `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, or `SSL_CERT_FILE`: optional CA bundle
  overrides for the Python TLS stack.
- `SMJ_STRICT_CERT`: optional labapi strict certificate
  toggle. Leave unset for labapi's default `strict_cert=True`; set to `0`,
  `false`, `no`, or `off` to call `labapi.Client(..., strict_cert=False)`.

## Defaults When Nothing Is Configured

If no repo config or notebook overrides are present, the backend falls back to:

- target notebook: `Jupyter Snapshots`
- target root path:
  `Notebook Log/{user_email}/{project_name}/{relative_notebook_path}`
- commit mode: `ask`
- tracked files: none
- notebook file included in snapshots
- diff included when the repo is dirty and no commit is created
- notebook and tracked files staged when a snapshot commit is created

## Repo Config

Put `.save-my-jupyter.toml` at the repo root.

Supported top-level sections:

- `[project]`
- `[defaults]`
- `[defaults.metadata]`
- `[labarchives]`
- `[git]`

## Full Example

```toml
[project]
name = "analysis-repo"
repo_root_strategy = "git"

[defaults]
all_cells_trigger = false
commit_mode = "ask"
watch_paths = []
include_notebook_file = true
include_diff_when_dirty = true

[defaults.metadata]
audience = "team"

[labarchives]
target_notebook = "Jupyter Snapshots"
target_root_path = "Notebook Log/{user_email}/{project_name}/{relative_notebook_path}"

[git]
stage_notebook_on_commit = true
stage_watched_paths_on_commit = true
commit_message_template = "snapshot: {notebook_name} {timestamp}"
```

## Section Reference

### `[project]`

- `name`
  Human-readable project name. Available in `target_root_path` as `{name}`.
- `repo_root_strategy`
  Must be `git` or `fixed`.

### `[defaults]`

- `all_cells_trigger`
  If true, automatic snapshots can fire for every executed cell.
- `commit_mode`
  Must be `ask`, `always`, or `never`. Legacy `prompt` values are accepted as
  `ask` for compatibility.
- `watch_paths`
  Default tracked-file paths to attach at snapshot time. Leave as `[]` when no
  extra files should be included by default.
- `include_notebook_file`
  Include the notebook file in every snapshot.
- `include_diff_when_dirty`
  Include a Git diff when no commit is created.

### `[defaults.metadata]`

Shared string metadata fields to add to every snapshot from this repo. Notebook
metadata can override individual keys for a specific notebook, and per-snapshot
panel fields override both.

Example:

```toml
[defaults.metadata]
audience = "team"
study = "memory"
```

### `[labarchives]`

- `target_notebook`
  Default LabArchives notebook name.
- `target_root_path`
  Default root path inside the LabArchives notebook. This is a Python format
  string with these substitutions:
  `{name}`, `{user_id}`, `{user_email}`, `{repo_name}`, `{notebook_name}`,
  `{notebook_stem}`, `{relative_notebook_path}`, `{scope_path}`,
  `{scope_name}`, `{run_label}`, `{experiment_context}`, `{timestamp}`,
  `{date}`, `{time}`, `{source}`, `{commit_hash}`.

`scope_path` is currently an alias for `relative_notebook_path`, and
`scope_name` is the final path segment of that value.

### `[git]`

- `stage_notebook_on_commit`
  Stage the notebook file when a snapshot commit is created.
- `stage_watched_paths_on_commit`
  Also stage tracked paths when a snapshot commit is created. Defaults to
  `true`.
- `commit_message_template`
  Python format string. Current implementation provides:
  - `{notebook_name}`
  - `{timestamp}`

## Tracked File Path Syntax

Tracked file paths must be relative.

Invalid values:

- absolute paths
- paths containing `..` that escape the root

This applies to:

- `[defaults].watch_paths`
- notebook metadata `watched_paths`

## Notebook Metadata

Notebook-local config is stored under the notebook metadata key
`save_my_jupyter`.

Supported fields:

```json
{
  "enabled": true,
  "all_cells_trigger": false,
  "trigger_cell_ids": ["cell-a", "cell-b"],
  "watched_paths": ["outputs", "reports/result.csv"],
  "labarchives_target_notebook": "Jupyter Snapshots",
  "labarchives_target_root_path": "Notebook Log/alice/reports/run1.ipynb",
  "default_metadata": {
    "owner": "alice"
  }
}
```

Cell-level trigger state is stored as:

```json
{
  "save_my_jupyter": {
    "trigger": true
  }
}
```

Notebook metadata is the supported way to override LabArchives destination or
metadata defaults for a specific notebook.

## User Settings

The frontend stores user defaults in Jupyter settings or local storage.

Supported fields:

- `defaultCommitMode`
- `rememberCommitChoice`
- `defaultTags`
- `defaultRunLabel`

These are user-local defaults. They should not be used for shared repo policy.
Older settings may still contain `defaultExperimentContext`; the frontend no
longer exposes it and normalizes snapshot requests to `null`.

To opt into tag extraction from metadata, add `tagme` to notebook
`default_metadata`. Its value can be comma-, semicolon-, or newline-separated,
and the backend merges those values into the snapshot tags while also retaining
the original extra field.

## Effective Config Resolution

The backend resolves:

- trigger mode
- commit mode
- tracked paths
- LabArchives target
- Git staging policy

Rules worth noting:

- notebook metadata overrides repo defaults
- notebook metadata target fields override repo targets
- a manual request can override commit mode
- if commit mode remains `ask`, the panel asks for the per-snapshot commit choice

## Recommended Team Layout

For a shared repo:

1. put `.save-my-jupyter.toml` at the repo root
2. leave tracked paths empty unless the team intentionally opts into them
3. define one shared default LabArchives destination in repo config
4. use notebook metadata only for notebook-specific overrides

## Validation Rules

The config parser rejects:

- invalid `repo_root_strategy` values
- invalid `commit_mode` values
- malformed field types
- unreadable or invalid TOML
