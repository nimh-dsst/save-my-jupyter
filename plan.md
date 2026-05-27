# Save My Jupyter: Implementation Plan

## Summary

Build a single Python-distributed Jupyter extension for JupyterLab 4.x and Notebook 7.x that captures notebook development snapshots and persists them to LabArchives.

The package contains:

- a Jupyter Server extension for orchestration, Git integration, file watching, config resolution, snapshot assembly, authentication, and LabArchives persistence
- a prebuilt JupyterLab frontend extension for notebook UI, trigger configuration, notebook metadata editing, user-entered metadata, and execution event capture

The canonical persisted unit is a snapshot. One snapshot becomes one LabArchives page.

Core behavior must be kernel-independent:

- the extension package installs only into the Jupyter server environment
- notebook kernels do not need the package installed
- core snapshot behavior must not depend on importing helper code into the kernel

## Compatibility Policy

### Server environment

Supported stack:

- JupyterLab 4.x
- Notebook 7.x
- Jupyter Server 2.x
- Python >= 3.12

Set:

- `requires-python = ">=3.12"`

This does not imply that notebook kernels must also run Python 3.12.

### Kernel environment

Core snapshot features must work without:

- installing `save-my-jupyter` into the kernel
- importing extension code in notebook cells
- using `IPython.get_ipython()`
- monkey-patching display hooks or `matplotlib`
- assuming the kernel is Python

Kernel-independent Tier 1 features:

- manual snapshots
- trigger-cell snapshots
- watched-path snapshots
- notebook file attachment
- Git commit and diff capture
- LabArchives persistence
- notebook and cell metadata configuration
- shared-repo path-rule routing

Optional Tier 2 enrichment may be added later, but it must never be required for snapshot success.

## Product Goals

The extension should make it easier to review notebook development history by capturing artifacts from the notebook development cycle, including:

- notebook code state
- notebook execution context
- visible output-derived figures and values
- files produced during runs
- user-entered metadata
- Git version context when available

The extension should work well for multiple users operating in one shared repository.

## Snapshot Model

### Snapshot sources

A snapshot may be initiated by:

- `manual`
- `trigger_cell`
- `watched_path`

### Manual snapshots

Manual snapshot always creates a new snapshot request.

### Trigger-cell snapshots

A trigger-cell snapshot fires only if:

- the executed cell is marked as a trigger, or notebook mode has `all_cells_trigger = true`
- the execution belongs to a new run boundary
- no snapshot has already been emitted for that run

If multiple trigger cells fire during one logical run, emit exactly one automatic snapshot.

### Watched-path snapshots

A watched-path snapshot fires only if:

- the changed path is inside the allowed root
- the path matches a configured watch rule
- the change belongs to a new run or change group not already captured

### Run semantics

Define a run as a contiguous execution episode for one notebook session.

Rules:

- one run may hit multiple trigger cells
- one automatic snapshot maximum is emitted per run
- manual snapshots bypass automatic dedupe
- watched-path and trigger-cell events for the same run may coalesce into one snapshot

The backend computes a `RunFingerprint` and uses it for dedupe.

## Git Behavior

Git is the canonical version anchor when available.

For each snapshot:

1. save the notebook to disk first
2. resolve effective commit mode from config precedence
3. if committing:
   - stage the notebook file
   - optionally stage in-scope watched paths per config
   - do not stage unrelated repository files
   - create a commit with the configured message template
4. if not committing:
   - snapshot still succeeds
   - generate a diff against `HEAD`
   - persist the diff as text and or a `.patch` artifact

The UI should support:

- `prompt`
- `always`
- `never`

Prompt behavior should include a persisted "always commit" preference. If the user declines to commit, the snapshot still proceeds and stores the dirty diff.

Support commit URL generation for:

- GitHub
- GitLab
- Bitbucket
- unknown generic fallback

Do not make provider-specific API calls in v1.

## Shared Repo Configuration

Use a repo-level `.save-my-jupyter.toml` file as the shared project contract.

Purpose:

- define shared defaults for teams working in one repository
- route different notebook subpaths to different LabArchives destinations
- define watched paths and attachment scopes
- define commit policy defaults
- define metadata templates

### Config precedence

Highest precedence first:

1. manual snapshot request overrides
2. notebook metadata
3. user settings
4. repo config: `.save-my-jupyter.toml`

### Repo config schema

Top-level sections:

- `[project]`
- `[defaults]`
- `[labarchives]`
- `[git]`
- `[[path_rule]]`

Suggested fields:

`[project]`

- `name: str`
- `repo_root_strategy: "git" | "fixed"`

`[defaults]`

- `all_cells_trigger: bool`
- `commit_mode: "prompt" | "always" | "never"`
- `watch_paths: list[str]`
- `include_notebook_file: bool`
- `include_diff_when_dirty: bool`

`[labarchives]`

- `target_notebook: str | null`
- `target_root_path: str | null`

`[git]`

- `stage_notebook_on_commit: bool`
- `stage_watched_paths_on_commit: bool`
- `commit_message_template: str`

`[[path_rule]]`

- `name: str`
- `match_paths: list[str]`
- `watch_paths: list[str]`
- `include_paths: list[str]`
- `exclude_paths: list[str]`
- `labarchives_target_notebook: str | null`
- `labarchives_target_root_path: str | null`
- `metadata_template: dict[str, str]`

### Path-rule semantics

A `path_rule` applies when the notebook repo-relative path matches one of its `match_paths`.

A resolved path rule determines:

- default watched paths
- in-scope attachment paths
- default LabArchives destination
- default metadata template

If multiple rules match:

- choose the most specific path prefix
- if still tied, treat config as invalid

## Notebook And User Configuration

### Notebook metadata

Store notebook-local config under a namespaced metadata key such as `save_my_jupyter`.

Fields:

- `enabled: bool`
- `all_cells_trigger: bool`
- `trigger_cell_ids: string[]`
- `watched_paths: string[]`
- `labarchives_target_notebook: string | null`
- `labarchives_target_root_path: string | null`
- `default_metadata: object`

### Cell metadata

Store trigger designation on cells:

- `save_my_jupyter.trigger: true`

The frontend should support:

- mark cell as trigger
- unmark cell as trigger
- toggle "all cells are triggers" at notebook level

### User settings

Store personal defaults in Jupyter settings:

- default commit mode
- remember commit choice
- default tags
- default run label
- default experiment context
- UI preferences only

## Architecture

### Frontend responsibilities

The frontend owns:

- notebook toolbar, commands, and panels
- trigger cell configuration
- notebook metadata updates
- user metadata forms
- execution event observation
- sending typed snapshot requests to the backend

The frontend does not own:

- Git inspection
- diff generation
- file watching
- LabArchives writes
- job orchestration

### Backend responsibilities

The backend owns:

- config loading and precedence resolution
- path-rule selection
- Git inspection, staging, commit creation, and diff generation
- watched-path registration and filesystem events
- queueing, dedupe, and run-boundary coordination
- LabArchives authentication and persistence
- artifact collection from notebook file and document-visible outputs

### Kernel boundary

The kernel is treated as opaque for core behavior.

The extension may observe notebook document state and visible outputs, but must not depend on:

- kernel-side package installation
- importing its own helper modules into the kernel
- Python-only runtime hooks

## Backend Package Layout

Recommended structure:

- `save_my_jupyter/`
- `save_my_jupyter/api.py`
- `save_my_jupyter/extension.py`
- `save_my_jupyter/config/`
- `save_my_jupyter/domain/`
- `save_my_jupyter/services/`
- `save_my_jupyter/adapters/`
- `save_my_jupyter/watchers/`
- `save_my_jupyter/git/`
- `save_my_jupyter/labarchives/`

## Frontend Package Layout

Recommended structure:

- `src/index.ts`
- `src/plugin.ts`
- `src/commands.ts`
- `src/metadata.ts`
- `src/panels/SnapshotPanel.tsx`
- `src/notebook/triggerHooks.ts`
- `src/notebook/requestBuilders.ts`
- `src/types.ts`

## Type System Strategy

### Design rule

Use parse-to-narrow as a core architectural rule.

All raw inputs must be parsed once into narrow domain types before entering core services.

Allowed raw boundaries:

- HTTP JSON request bodies
- TOML config from `.save-my-jupyter.toml`
- notebook metadata maps
- Jupyter frontend model objects
- file watch events
- Git command output
- LabArchives API responses inside the adapter only

No core service may accept:

- `dict[str, Any]`
- raw JSON
- raw TOML structures
- partially parsed notebook metadata

### Python typing rules

Use:

- `NewType` for identifiers and normalized paths
- `StrEnum` for wire-facing enums
- frozen, slotted dataclasses for immutable domain models
- `Protocol` for service boundaries
- discriminated unions for request and artifact variants

Avoid:

- `Any` outside parser and adapter internals
- optional field bags when a discriminated union is more precise

### Example narrow identity and path types

Use `NewType` for:

- `UserId`
- `NotebookPath`
- `RepoRootPath`
- `RelativeRepoPath`
- `RelativeWatchPath`
- `DocumentId`
- `KernelId`
- `CellId`
- `SnapshotId`
- `RunFingerprint`
- `CommitHash`
- `RemoteUrl`
- `LabArchivesNotebookName`
- `LabArchivesRootPath`
- `MimeType`

### Enums

Use `StrEnum` for:

- `SnapshotSource`
- `CommitMode`
- `PathEventType`
- `ArtifactKind`
- `TriggerMode`
- `RepoHost`

## Domain Models

Use frozen, slotted dataclasses for:

- `UserMetadata`
- `WatchedPathEvent`
- `NotebookContext`
- `ResolvedRepoContext`
- `LabArchivesTarget`
- `ResolvedPathRule`
- `NotebookMetadataConfig`
- `UserSettingsConfig`
- `RepoConfig`
- `EffectiveConfig`
- `ResolvedSnapshotPlan`
- `SnapshotRecord`

### Request union

Use a discriminated union keyed by `source`:

- `ManualSnapshotRequest`
- `TriggerCellSnapshotRequest`
- `WatchedPathSnapshotRequest`

Union:

- `SnapshotRequest = ManualSnapshotRequest | TriggerCellSnapshotRequest | WatchedPathSnapshotRequest`

### Artifact union

Use a discriminated union keyed by `kind`:

- `NotebookArtifact`
- `FigureArtifact`
- `FileArtifact`
- `DiffArtifact`

Union:

- `ArtifactRef = NotebookArtifact | FigureArtifact | FileArtifact | DiffArtifact`

### Result unions

Use discriminated result types:

- `SnapshotAccepted`
- `SnapshotRejected`
- `SnapshotPersisted`
- `SnapshotFailed`

## Parser Modules And Functions

Create dedicated parser modules:

- `api/parsers.py`
- `config/parsers.py`
- `notebook/parsers.py`
- `watchers/parsers.py`
- `git/parsers.py`

Required functions:

- `parse_snapshot_request(raw: RawSnapshotRequest) -> SnapshotRequest`
- `parse_repo_config(raw: RawRepoConfig, repo_root: RepoRootPath) -> RepoConfig`
- `parse_notebook_metadata(raw: RawNotebookMetadata) -> NotebookMetadataConfig`
- `parse_user_settings(raw: RawUserSettings) -> UserSettingsConfig`
- `parse_watch_event(raw: RawWatchEvent, root: RepoRootPath | NotebookPath) -> WatchedPathEvent | None`
- `parse_git_remote(raw: str | None) -> tuple[RepoHost, RemoteUrl | None]`
- `normalize_watch_path(...) -> RelativeWatchPath`
- `normalize_repo_relative_path(...) -> RelativeRepoPath`
- `parse_commit_hash(...) -> CommitHash | None`
- `parse_cell_id(...) -> CellId`
- `parse_notebook_path(...) -> NotebookPath`

## Service Protocols

Use `Protocol` for:

- `ConfigProvider`
- `GitService`
- `WatchService`
- `ArtifactCollector`
- `SnapshotWriter`
- `AuthService`

## Concrete Backend Classes

Implement:

- `ExtensionApp`
- `ConfigService`
- `RunFingerprintService`
- `SnapshotCoordinator`
- `NotebookSnapshotQueue`
- `SnapshotService`
- `DefaultGitService`
- `DefaultWatchService`
- `DocumentArtifactCollector`
- `LabArchivesAdapter`
- `AuthServiceImpl`

### Responsibilities

`ExtensionApp`

- bootstraps the server extension
- wires dependencies
- registers HTTP handlers

`ConfigService`

- discovers repo config
- parses config
- resolves path rules
- merges config layers
- validates conflicts

`RunFingerprintService`

- computes run boundaries
- decides whether two requests belong to the same run

`SnapshotCoordinator`

- owns per-notebook queues
- dedupes automatic requests
- coalesces trigger hits within one run

`NotebookSnapshotQueue`

- serializes jobs for one notebook or session
- tracks pending and running jobs
- tracks recent run fingerprints

`SnapshotService`

- plans a snapshot
- executes a snapshot
- persists a snapshot

`DefaultGitService`

- resolves repo context
- stages allowed files
- creates commits
- generates diff against `HEAD`
- derives commit URLs

`DefaultWatchService`

- registers watches
- normalizes file events
- emits typed watched-path events

`DocumentArtifactCollector`

- collects kernel-independent artifacts only
- notebook file
- visible output-derived figures
- visible text/plain summaries
- watched files
- diff artifact

`LabArchivesAdapter`

- uses `labarchives-api`
- resolves the LabArchives target
- creates directory tree
- creates snapshot pages
- writes entries and uploads attachments

`AuthServiceImpl`

- manages per-user interactive LabArchives auth sessions in memory

## Backend Methods

`SnapshotCoordinator`

- `submit(request: SnapshotRequest, user_id: UserId) -> SnapshotAccepted | SnapshotRejected`
- `coalesce_trigger(queue: NotebookSnapshotQueue, request: SnapshotRequest) -> bool`

`NotebookSnapshotQueue`

- `enqueue(plan: ResolvedSnapshotPlan) -> None`
- `start_next() -> ResolvedSnapshotPlan | None`
- `mark_complete(run_fingerprint: RunFingerprint) -> None`
- `has_seen_run(run_fingerprint: RunFingerprint) -> bool`

`SnapshotService`

- `plan_snapshot(request: SnapshotRequest, user_id: UserId) -> ResolvedSnapshotPlan`
- `execute_snapshot(plan: ResolvedSnapshotPlan, user_id: UserId) -> SnapshotRecord`
- `persist_snapshot(record: SnapshotRecord, user_id: UserId) -> SnapshotPersisted | SnapshotFailed`

`ConfigService`

- `find_repo_config(notebook_path: NotebookPath) -> Path | None`
- `load_repo_config(notebook_path: NotebookPath) -> RepoConfig | None`
- `resolve_path_rule(repo_config: RepoConfig, notebook_relpath: RelativeRepoPath) -> ResolvedPathRule | None`
- `merge_config_layers(...) -> EffectiveConfig`
- `validate_repo_config(repo_config: RepoConfig) -> None`

## Frontend Types And Classes

Use strict TypeScript discriminated unions and parsed state models.

Required frontend types:

- `SnapshotSource`
- `CommitMode`
- `NotebookExtensionMetadata`
- `CellExtensionMetadata`
- `SnapshotRequestPayload`
- `EffectiveState`
- `SnapshotSubmissionResult`

Implement frontend classes:

- `SnapshotPlugin`
- `SnapshotPanelModel`
- `NotebookMetadataStore`
- `ExecutionObserver`
- `ApiClient`

### Frontend responsibilities

`SnapshotPlugin`

- activates the extension
- registers commands
- installs toolbar and menu integrations
- wires observers and panel model

`SnapshotPanelModel`

- owns local UI state
- loads effective state from backend
- saves notebook metadata
- submits manual snapshot requests

`NotebookMetadataStore`

- reads and writes notebook metadata
- reads and writes trigger cell metadata

`ExecutionObserver`

- listens to execution completion events
- determines trigger eligibility from parsed metadata
- builds trigger snapshot requests

`ApiClient`

- calls backend endpoints
- parses backend responses before returning typed state

### Frontend functions

- `parseSnapshotRequestPayload(raw): SnapshotRequestPayload`
- `parseEffectiveState(raw): EffectiveState`
- `readNotebookMetadata(panel): NotebookExtensionMetadata`
- `readCellMetadata(cell): CellExtensionMetadata`
- `buildManualSnapshotPayload(...): ManualSnapshotRequestPayload`
- `buildTriggerCellSnapshotPayload(...): TriggerCellSnapshotRequestPayload`
- `validateWatchedPath(path: string): ValidationResult`

## Artifact Collection Policy

### Required v1 artifacts

Every snapshot must be able to include:

- saved notebook file
- snapshot metadata
- Git metadata
- commit hash and commit URL when available
- diff against `HEAD` when no commit is created
- watched files that changed
- path-rule and user metadata
- limited execution context from frontend-visible notebook events

### Optional v1 artifacts

These may be included only if derivable without kernel coupling:

- image outputs already present in notebook output model
- text/plain result summaries already present in output model
- frontend-visible widget state only if available without kernel-specific assumptions

### Out of scope for core v1

Do not require:

- Python object introspection inside the kernel
- generic capture of arbitrary in-memory objects
- generic capture of arbitrary frontend interactions not represented in the notebook model or extension UI

## LabArchives Mapping

Only `LabArchivesAdapter` may call `labarchives-api`.

The rest of the system emits a storage-agnostic `SnapshotRecord`.

### Target path

Default target tree:

`<target notebook>/<target root>/<user id>/<path rule name or repo name>/<timestamp>`

Path rules may override:

- target notebook
- target root path

### One page per snapshot

Each page contains entries in stable order:

1. summary entry
2. metadata entry
3. Git info entry
4. execution and value summary entry
5. diff entry or diff attachment if dirty
6. notebook attachment
7. figure attachments
8. file attachments

## Authentication

Use per-user interactive LabArchives authentication in the server extension.

Rules:

- backend stores authenticated LabArchives sessions in memory
- snapshots are rejected if persistence is requested and the user is not authenticated
- no shared service account assumption in v1

## Runtime State

Keep runtime state in memory only for v1.

In-memory state includes:

- active authenticated LabArchives sessions per Jupyter user
- active notebook coordinators keyed by notebook or session identity
- queued and running snapshot jobs
- recent run fingerprints for dedupe
- active watched-path registrations

No database in v1.

No background retry system in v1.

If a LabArchives write fails:

- the job fails
- the error is returned to the frontend
- the user may retry manually

## Validation And Failure Handling

### Fail fast on

- invalid notebook path
- watched path escaping allowed root
- malformed request body
- malformed repo config
- conflicting path-rule resolution
- missing LabArchives auth when persistence is attempted

### Degraded but successful operation

Snapshot should still succeed when:

- there is no Git repository
- the user declines commit
- there is no remote URL
- there are no figures
- a watched file disappears before attachment read, with warning recorded

## Python Quality Policy

### Tools

Require:

- `ruff` for formatting and linting
- `ty`
- `pyright` strict mode if retained
- `pytest`

### Ruff

Use Ruff as the canonical formatter and linter.

Enable at minimum:

- `E`
- `F`
- `W`
- `I`
- `N`
- `UP`
- `B`
- `A`
- `C4`
- `DTZ`
- `EM`
- `FA`
- `ICN`
- `LOG`
- `G`
- `PIE`
- `PT`
- `PTH`
- `RET`
- `RSE`
- `RUF`
- `SIM`
- `SLOT`
- `TC`

Optional if they fit cleanly:

- `ARG`
- `BLE`
- `COM`
- `ERA`
- `ISC`
- `PERF`
- `PGH`
- `TRY`

Use:

- `target-version = "py312"`

Rules:

- no untyped defs in core modules
- no unused imports or variables
- no raw path string manipulation where `pathlib` is appropriate
- no broad exception swallowing
- no mutable default arguments
- minimal `cast()`

### Ty

Require:

- repo-wide Python type checking
- narrow boundary validation before service logic
- consistent type checking in CI and local development

### Python syntax policy

Use the newest Python 3.12-compatible syntax:

- `from __future__ import annotations`
- `StrEnum`
- `Protocol`
- `Self`
- `Literal`
- `assert_never`
- modern union syntax
- frozen, slotted dataclasses

Do not use 3.13+ only syntax in v1.

## TypeScript Quality Policy

### Tools

Require:

- `tsc --noEmit`
- `eslint`
- frontend tests
- one canonical formatter, either `prettier` or the repo's established formatter

### TypeScript compiler settings

Require:

- `"strict": true`
- `"noUncheckedIndexedAccess": true`
- `"exactOptionalPropertyTypes": true`
- `"noImplicitOverride": true`
- `"noImplicitReturns": true`
- `"noFallthroughCasesInSwitch": true`
- `"useUnknownInCatchVariables": true`
- `"noPropertyAccessFromIndexSignature": true`

Preferred if compatible:

- `"verbatimModuleSyntax": true`
- `"isolatedModules": true`

### ESLint

Use:

- `typescript-eslint`
- `eslint-plugin-import`
- `eslint-plugin-react`
- `eslint-plugin-react-hooks`
- `eslint-plugin-unused-imports`
- `eslint-config-prettier` if using Prettier

Enforce:

- no `any`
- no floating promises
- no unused imports or variables
- exhaustive union handling
- import order
- hooks rules
- no unsafe unchecked JSON member access
- no unnecessary type assertions

### Frontend type rules

- parse backend JSON with runtime schemas, preferably `zod`
- parse notebook metadata before use
- do not store raw JSON in UI state
- do not rely on unchecked casts from Jupyter objects into app models
- avoid non-null assertions except at rare, documented adapter seams

## Test Policy

### Philosophy

Tests must enforce:

- type boundary correctness
- kernel independence of core behavior
- snapshot correctness
- shared-repo routing correctness
- strict lint and type discipline

### 1. Parser and type tests

Required:

- malformed HTTP payload rejected
- malformed TOML rejected
- invalid paths rejected
- impossible discriminated union combinations rejected
- raw notebook metadata parsed or rejected correctly
- service tests do not pass raw dicts directly

### 2. Backend unit tests

Required:

- config precedence resolution
- path-rule specificity resolution
- run fingerprint generation
- dedupe of multiple trigger hits in one run
- queue coalescing
- repo discovery
- constrained staging behavior
- diff generation without commit
- commit URL derivation
- artifact collection filtered by path rule
- LabArchives mapping logic

### 3. Frontend unit tests

Required:

- notebook metadata read and write
- cell trigger metadata toggling
- watched path validation
- payload builders for manual and trigger snapshots
- parsed backend state loading
- exhaustive handling of result unions

### 4. Kernel-independence tests

Required:

- snapshot works without installing extension in kernel
- snapshot works without importing extension code in kernel
- notebook with older Python kernel still supports Tier 1 features
- notebook with non-Python kernel still supports Tier 1 features
- no core code path depends on `IPython.get_ipython()` or kernel monkey-patching

### 5. Integration tests

Required:

- manual snapshot with commit
- manual snapshot without commit
- multiple trigger hits in one run produce one snapshot
- watched-path-triggered snapshot
- shared repo with multiple path rules routes correctly
- multiple users in one repo with different notebook subpaths get different defaults
- LabArchives page creation includes expected entries and attachments

### 6. Packaging tests

Required:

- one wheel installs backend and frontend assets
- extension loads in JupyterLab 4
- extension loads in Notebook 7
- server package works on Python 3.12
- no kernel-side install requirement

## CI Policy

CI must fail if any of these fail:

- `ruff format --check`
- `ruff check`
- `ty check`
- `pyright` if retained
- `tsc --noEmit`
- `eslint`
- backend tests
- frontend tests
- integration tests selected for the CI tier

Minimum CI jobs:

- Python 3.12 lint, type, and test
- frontend lint, type, and test
- optional Python 3.13 compatibility job if dependencies allow

## Acceptance Criteria

The implementation satisfies the plan only if:

- the server package requires Python `>=3.12`
- kernels do not need the package installed
- core features remain kernel-independent
- `.save-my-jupyter.toml` drives shared-repo routing
- config precedence is deterministic
- all external inputs are parsed into narrow types before service use
- one logical run produces at most one automatic snapshot
- declining commit still preserves diff against `HEAD`
- one snapshot produces one LabArchives page with stable entry ordering
- strict Python and TypeScript quality gates are enforced in CI

## Notes From Planning Session

These constraints came directly from the planning session and should not be dropped during implementation:

- use `labarchives-api` from `~/projects/labarchives-api` as the backend integration layer
- the extension is intended to preserve artifacts from the Jupyter notebook development cycle
- snapshot capture should cover notebook code state, files, output figures, visible produced values, and user-inputted metadata
- snapshots should support both explicit save and automatic triggers
- trigger cells should be stored in cell metadata, but the UI should still support "all cells are triggers"
- watched paths should be user-configured relative paths
- Git should be the canonical version anchor when available
- if the user declines commit, still save data and preserve code changes as a diff against the last commit
- one shared repo may have multiple users and multiple path areas of interest, which is why `.save-my-jupyter.toml` uses path-based rules
- implementation should be strongly type-constrained with parsing to narrow domain types
- Python syntax should be as modern as possible while remaining compatible with the chosen Jupyter server stack
- strict linting, type checking, Ruff rules, and strict TypeScript linting are required from the beginning
