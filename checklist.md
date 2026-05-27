# Save My Jupyter: Implementation Checklist

This checklist turns [plan.md](C:\Users\licc\projects\save-my-jupyter\plan.md) into an implementation order.

## Phase 0: Repo And Tooling Bootstrap

- [x] Create the base project structure for a single Python-distributed Jupyter extension
- [x] Add `pyproject.toml` with `requires-python = ">=3.12"`
- [x] Add frontend package metadata and build scripts
- [x] Configure Ruff as the canonical Python formatter and linter
- [x] Configure `ty`
- [x] Configure `pyright` strict mode if retained
- [x] Configure TypeScript strict mode
- [x] Configure ESLint for TypeScript, React, and Jupyter frontend code
- [x] Add test runners and CI-oriented scripts
- [x] Add pre-commit or equivalent local quality gate hooks if desired

### Exit criteria

- [x] Python lint, format, and typecheck commands exist
- [x] Frontend lint, format, and typecheck commands exist
- [x] Test commands exist for backend and frontend

## Phase 1: Domain Types And Parsing Foundation

- [x] Create the domain package for narrow typed models
- [x] Define `NewType` identities and normalized path types
- [x] Define `StrEnum` values for snapshot sources, commit modes, artifact kinds, trigger modes, path event types, and repo hosts
- [x] Implement frozen, slotted dataclasses for core domain models
- [x] Implement discriminated unions for snapshot request variants
- [x] Implement discriminated unions for artifact variants
- [x] Implement discriminated result unions for snapshot submission and persistence results
- [x] Create parser modules for API, config, notebook metadata, watcher events, and Git outputs
- [x] Implement path normalization helpers
- [x] Implement config validation errors and parse errors

### Exit criteria

- [x] No core service needs raw JSON or raw TOML
- [x] All boundary parsers have direct unit tests
- [x] Invalid boundary inputs fail before reaching service logic

## Phase 2: Shared Repo Config And Effective Config Resolution

- [x] Define the `.save-my-jupyter.toml` schema in typed models
- [x] Implement repo config discovery from notebook path
- [x] Implement repo config parsing
- [x] Implement validation for duplicate or conflicting path rules
- [x] Implement path-rule specificity resolution
- [x] Implement user settings parsing
- [x] Implement notebook metadata parsing
- [x] Implement config precedence merge:
- [x] Manual request overrides
- [x] Notebook metadata
- [x] User settings
- [x] Repo config
- [x] Implement effective target resolution for LabArchives notebook and root path
- [x] Implement effective watched-path resolution
- [x] Implement effective commit-mode resolution

### Exit criteria

- [x] A notebook path resolves deterministically to zero or one path rule
- [x] Effective config is fully typed and free of raw values
- [x] Conflicting config produces a hard validation error

## Phase 3: Backend Skeleton And HTTP Surface

- [x] Create the server extension bootstrap class
- [x] Wire dependency injection for core backend services
- [x] Add HTTP handlers for:
- [x] `GET /state`
- [x] `POST /snapshot`
- [x] `POST /auth/start`
- [x] `GET /auth/status`
- [x] Add request parsing and response typing at the HTTP boundary
- [x] Define backend error mapping into structured API responses

### Exit criteria

- [x] Server extension loads in Jupyter Server
- [x] Each route accepts only parsed input models
- [x] Each route returns typed success and failure responses

## Phase 4: Frontend Skeleton And Notebook Integration

- [x] Create the JupyterLab frontend plugin
- [x] Register commands for:
- [x] Snapshot now
- [x] Mark cell as trigger
- [x] Unmark cell as trigger
- [x] Toggle all cells as triggers
- [x] Open snapshot settings
- [x] Add toolbar button integration
- [x] Add notebook metadata store helpers
- [x] Add cell metadata store helpers
- [x] Add a settings or side panel UI for snapshot configuration
- [x] Add frontend API client
- [x] Add runtime schema parsing for backend responses

### Exit criteria

- [x] The plugin activates in JupyterLab
- [x] Trigger metadata can be read and written
- [x] Snapshot UI can load typed state from the backend

## Phase 5: Run Detection And Snapshot Queueing

- [x] Implement `RunFingerprintService`
- [x] Define notebook or session identity for queue keys
- [x] Implement `NotebookSnapshotQueue`
- [x] Implement `SnapshotCoordinator`
- [x] Implement dedupe rules for automatic triggers
- [x] Implement coalescing of multiple trigger hits in the same run
- [x] Ensure manual snapshots bypass automatic dedupe

### Exit criteria

- [x] Multiple trigger cells in one run produce one automatic snapshot
- [x] Manual snapshots always enqueue
- [x] Queue behavior is deterministic and unit tested

## Phase 6: Git Integration

- [x] Implement repo discovery from notebook path
- [x] Implement remote URL parsing and host detection
- [x] Implement commit URL generation for GitHub, GitLab, Bitbucket, and unknown fallback
- [x] Implement constrained staging logic
- [x] Stage notebook file only by default
- [x] Optionally stage in-scope watched files per config
- [x] Do not stage unrelated repository files
- [x] Implement commit creation with configurable message template
- [x] Implement diff generation against `HEAD`
- [x] Implement no-repo mode behavior

### Exit criteria

- [x] Snapshot works in Git and no-Git repositories
- [x] Declining commit still produces a diff artifact or diff entry
- [x] Staging behavior cannot accidentally commit unrelated files

## Phase 7: File Watching

- [x] Implement `DefaultWatchService`
- [x] Support user-configured relative watched paths only
- [x] Resolve paths against repo root or notebook directory
- [x] Reject paths that escape the allowed root
- [x] Support watched files
- [x] Support watched directory subtrees
- [x] Normalize file events into typed watched-path events
- [x] Map watched-path events to notebook scope and snapshot requests

### Exit criteria

- [x] Watched-path changes can trigger snapshots
- [x] Invalid watched paths fail validation
- [x] File events are typed before entering snapshot logic

## Phase 8: Artifact Collection

- [x] Implement `DocumentArtifactCollector`
- [x] Collect notebook file artifact
- [x] Collect diff artifact when needed
- [x] Collect watched file artifacts
- [x] Collect visible output-derived figures when available through notebook state
- [x] Collect visible text or value summaries when available through notebook state
- [x] Keep artifact collection kernel-independent
- [x] Do not require kernel-side imports or monkey-patching

### Exit criteria

- [x] A snapshot can be assembled without any kernel-side package
- [x] Core artifacts work for kernel-independent Tier 1 behavior
- [x] Optional artifacts degrade gracefully when not available

## Phase 9: LabArchives Integration

- [x] Implement `AuthServiceImpl` for per-user interactive LabArchives sessions
- [x] Implement `LabArchivesAdapter` using `labarchives-api`
- [x] Resolve LabArchives target notebook and root path
- [x] Create the directory tree for a snapshot target
- [x] Create one LabArchives page per snapshot
- [x] Write entries in stable order:
- [x] Summary entry
- [x] Metadata entry
- [x] Git info entry
- [x] Execution or value summary entry
- [x] Diff entry or diff attachment
- [x] Notebook attachment
- [x] Figure attachments
- [x] File attachments
- [x] Return typed persistence results

### Exit criteria

- [x] One snapshot produces one LabArchives page
- [x] Page ordering is deterministic
- [x] Backend persistence logic is isolated behind the adapter

## Phase 10: End-To-End Snapshot Service

- [x] Implement `SnapshotService.plan_snapshot`
- [x] Implement `SnapshotService.execute_snapshot`
- [x] Implement `SnapshotService.persist_snapshot`
- [x] Ensure effective config, Git context, artifact collection, and LabArchives target resolution all flow through typed models
- [x] Ensure snapshot execution succeeds in degraded modes:
- [x] No Git repo
- [x] No commit chosen
- [x] No figures
- [x] Missing remote URL
- [x] Watched file removed before read
- [x] Ensure failure handling is structured and surfaced cleanly to the frontend

### Exit criteria

- [x] Manual snapshots work end to end
- [x] Trigger-cell snapshots work end to end
- [x] Watched-path snapshots work end to end

## Phase 11: Frontend Snapshot UX

- [x] Implement manual snapshot flow
- [x] Implement commit prompt UX with remember-choice behavior
- [x] Implement trigger-cell execution observation
- [x] Implement all-cells-trigger notebook mode
- [x] Implement watched-path editing UI
- [x] Implement user metadata fields:
- [x] Tags
- [x] Notes
- [x] Run label
- [x] Experiment context
- [x] Surface typed success and failure states to the user

### Exit criteria

- [x] User can configure notebook triggers from the UI
- [x] User can configure watched paths from the UI
- [x] User can submit manual snapshots without using code cells

## Phase 12: Strict Quality Gates

- [x] Enforce Ruff format and lint in CI
- [x] Enforce `ty` in CI
- [x] Enforce pyright strict in CI if retained
- [x] Enforce `tsc --noEmit` in CI
- [x] Enforce ESLint in CI
- [x] Ensure tests run in CI for backend and frontend
- [x] Minimize and document any lint or type ignores
- [x] Ensure no core service accepts raw dictionaries
- [x] Ensure no core path depends on `IPython.get_ipython()`

### Exit criteria

- [x] Static quality gates are required for merge
- [x] Core modules are free of type and lint debt

## Phase 13: Test Coverage

### Parser and type tests

- [x] Malformed HTTP payload rejected
- [x] Malformed TOML rejected
- [x] Invalid paths rejected
- [x] Impossible discriminated union combinations rejected
- [x] Raw notebook metadata parsed or rejected correctly

### Backend unit tests

- [x] Config precedence resolution
- [x] Path-rule specificity resolution
- [x] Run fingerprint generation
- [x] Automatic trigger dedupe
- [x] Queue coalescing
- [x] Repo discovery
- [x] Constrained staging behavior
- [x] Diff generation without commit
- [x] Commit URL derivation
- [x] Artifact filtering by path rule
- [x] LabArchives mapping logic

### Frontend unit tests

- [x] Notebook metadata read and write
- [x] Cell trigger metadata toggling
- [x] Watched path validation
- [x] Manual snapshot payload building
- [x] Trigger snapshot payload building
- [x] Parsed backend state loading
- [x] Exhaustive handling of result unions

### Kernel-independence tests

- [x] Snapshot works without installing the extension in the kernel
- [x] Snapshot works without importing extension code in the kernel
- [x] Older Python kernel still supports Tier 1 behavior
- [x] Non-Python kernel still supports Tier 1 behavior
- [x] No core code path depends on kernel monkey-patching

### Integration tests

- [x] Manual snapshot with commit
- [x] Manual snapshot without commit
- [x] Multiple trigger hits in one run produce one snapshot
- [x] Watched-path-triggered snapshot
- [x] Shared repo with multiple path rules routes correctly
- [x] Multiple users in one repo with different notebook subpaths get different defaults
- [x] LabArchives page contains expected entries and attachments

### Packaging tests

- [x] One wheel installs backend and frontend assets
- [x] Extension loads in JupyterLab 4
- [x] Extension loads in Notebook 7
- [x] Server package works on Python 3.12
- [x] No kernel-side install requirement

## Phase 14: Final Acceptance Review

- [x] Server package requires Python >= 3.12
- [x] Kernels do not need the package installed
- [x] Core features remain kernel-independent
- [x] `.save-my-jupyter.toml` drives shared-repo routing
- [x] Config precedence is deterministic
- [x] All external inputs are parsed into narrow types before service use
- [x] One logical run produces at most one automatic snapshot
- [x] Declining commit still preserves diff against `HEAD`
- [x] One snapshot produces one LabArchives page with stable entry ordering
- [x] Strict Python and TypeScript quality gates are enforced in CI

## Implementation Notes

- [x] Use `labarchives-api` from `~/projects/labarchives-api` as the backend integration layer
- [x] Keep all core behavior kernel-independent
- [x] Preserve the path-rule model for multiple users in one repo
- [x] Keep all service interfaces typed and narrow
- [x] Do not defer lint or type discipline to a later cleanup pass
