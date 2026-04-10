# Configuration

## Overview

Configuration is merged from four layers, highest precedence first:

1. manual snapshot request overrides
2. notebook metadata
3. user settings
4. repo config in `.save-my-jupyter.toml`

This lets a shared repository define stable defaults while still allowing
notebook-local and user-local overrides.

## Defaults When Nothing Is Configured

If no repo config or notebook overrides are present, the backend falls back to:

- target notebook: `Jupyter Snapshots`
- target root path: `Notebook Log`
- commit mode: `prompt`, then user settings, then repo defaults if present
- notebook file included in snapshots
- diff included when the repo is dirty and no commit is created

## Repo Config

Put `.save-my-jupyter.toml` at the repo root.

Supported top-level sections:

- `[project]`
- `[defaults]`
- `[labarchives]`
- `[git]`
- `[[path_rule]]`

## Full Example

```toml
[project]
name = "analysis-repo"
repo_root_strategy = "git"

[defaults]
all_cells_trigger = false
commit_mode = "prompt"
watch_paths = ["outputs", "reports/latest.csv"]
include_notebook_file = true
include_diff_when_dirty = true

[labarchives]
target_notebook = "Jupyter Snapshots"
target_root_path = "Team A"

[git]
stage_notebook_on_commit = true
stage_watched_paths_on_commit = false
commit_message_template = "snapshot: {notebook_name} {timestamp}"

[[path_rule]]
name = "analysis"
match_paths = ["analysis"]
watch_paths = ["analysis/outputs"]
include_paths = ["analysis/outputs"]
exclude_paths = ["analysis/tmp"]
labarchives_target_notebook = "Jupyter Snapshots"
labarchives_target_root_path = "Analysis"

[path_rule.metadata_template]
owner = "analysis-team"
project = "baseline-study"

[[path_rule]]
name = "reports"
match_paths = ["reports"]
watch_paths = ["reports/generated"]
labarchives_target_root_path = "Reports"
```

## Section Reference

### `[project]`

- `name`
  Human-readable project name.
- `repo_root_strategy`
  Must be `git` or `fixed`.

### `[defaults]`

- `all_cells_trigger`
  If true, automatic snapshots can fire for every executed cell.
- `commit_mode`
  Must be `prompt`, `always`, or `never`.
- `watch_paths`
  Default relative paths to watch.
- `include_notebook_file`
  Include the notebook file in every snapshot.
- `include_diff_when_dirty`
  Include a Git diff when no commit is created.

### `[labarchives]`

- `target_notebook`
  Default LabArchives notebook name.
- `target_root_path`
  Default root path inside the LabArchives notebook.

### `[git]`

- `stage_notebook_on_commit`
  Stage the notebook file when a snapshot commit is created.
- `stage_watched_paths_on_commit`
  Also stage watched paths when a snapshot commit is created.
- `commit_message_template`
  Python format string. Current implementation provides:
  - `{notebook_name}`
  - `{timestamp}`

### `[[path_rule]]`

Path rules allow different repo subtrees to have different defaults.

- `name`
  Unique rule name.
- `match_paths`
  Relative repo paths that activate the rule.
- `watch_paths`
  Rule-specific watched paths.
- `include_paths`
  Paths that are in scope for attachments.
- `exclude_paths`
  Paths excluded from attachment scope.
- `labarchives_target_notebook`
  Rule-specific LabArchives notebook override.
- `labarchives_target_root_path`
  Rule-specific LabArchives root path override.
- `metadata_template`
  Default metadata values for notebooks matching the rule.

## Path-Rule Targeting Example

This is the intended shared-repo pattern:

- notebooks under `analysis/` route to one LabArchives subtree
- notebooks under `reports/` route to another
- each area can watch different artifact folders
- users still keep notebook-local trigger cells and metadata overrides

## Matching Rules

Path rules are matched against the notebook's repo-relative path.

Behavior:

- the most specific matching prefix wins
- duplicate rule names are rejected
- tied specificity is treated as a validation error

## Allowed Path Syntax

All path-like config values must be relative.

Invalid values:

- absolute paths
- paths containing `..` that escape the root

This applies to:

- `watch_paths`
- `include_paths`
- `exclude_paths`
- `match_paths`

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
  "labarchives_target_root_path": "Notebook Log",
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

## User Settings

The frontend stores user defaults in Jupyter settings or local storage.

Supported fields:

- `defaultCommitMode`
- `rememberCommitChoice`
- `defaultTags`
- `defaultRunLabel`
- `defaultExperimentContext`

These are user-local defaults. They should not be used for shared repo policy.

## Effective Config Resolution

The backend resolves:

- trigger mode
- commit mode
- watched paths
- LabArchives target
- metadata template
- Git staging policy

Rules worth noting:

- notebook metadata overrides repo defaults
- notebook metadata target fields override repo and path-rule targets
- a manual request can override commit mode
- if commit mode remains `prompt`, user settings are applied before repo defaults

## Recommended Team Layout

For a shared repo:

1. put `.save-my-jupyter.toml` at the repo root
2. create one `path_rule` per major notebook area
3. keep watched paths narrow
4. route each path rule to a distinct LabArchives subtree
5. use notebook metadata only for notebook-specific overrides

## Validation Rules

The config parser rejects:

- duplicate path-rule names
- invalid `repo_root_strategy` values
- invalid `commit_mode` values
- non-relative watch/include/exclude/match paths
- path values that normalize outside the allowed root

Config parsing happens before the core services use the values, so invalid
configuration fails early instead of producing partially typed runtime state.
