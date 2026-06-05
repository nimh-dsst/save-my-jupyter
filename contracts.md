# User Contracts

Each contract below is one paragraph describing observable behavior — the happy path, what the user sees if it breaks, and what happens if the recovery itself breaks. No motivations, no implementation rationale. Qualifiers like *atomic*, *automatic*, *silent*, *best effort*, *guaranteed*, and *opt-in* carry meaning: they tell the user what kind of promise is being made.

Stable IDs (`C-AUTH-03`, `C-WATCH-05`, …) let us reference contracts during design discussions. Areas are organized roughly by where the user encounters them.

"User" means a notebook author working inside JupyterLab unless otherwise noted. "Admin" means whoever installs the extension on the Jupyter server. "Team" means a group sharing one repository.

---

## SETUP — Installation & Compatibility

**C-SETUP-01.** Save My Jupyter installs as one Python package. `pip install save-my-jupyter` brings the Jupyter Server extension, the JupyterLab front-end labextension, and the `labapi` dependency in a single step. After the next server restart, the side panel and command-palette entries are available; no `jupyter server extension enable` step is required.

**C-SETUP-02.** The extension runs without requiring the notebook kernel to install this package or import extension code. Python kernels have one narrow live-state exception: immediately before a manual or trigger snapshot is submitted, the frontend makes a hidden best-effort read of `smj_tags` and `smj_run` from the current kernel. Non-Python kernels, missing kernels, malformed values, and read failures fall back to the static metadata path without blocking the snapshot.

**C-SETUP-03.** The supported stack is Python 3.10+, JupyterLab 4.x or Notebook 7.x, and Jupyter Server 2.x. Installs against older versions fail at the package level rather than at runtime.

**C-SETUP-04.** Server-side LabArchives credentials are an admin concern, not a user concern. The admin sets `ACCESS_KEYID` and `ACCESS_PWD` in the Jupyter server's process environment, or in a `.env` file at the Jupyter server root that Save My Jupyter loads at startup without overriding already-set process variables. The admin may optionally override `API_URL` (default `https://api.labarchives.com`) and the TLS bundle via `REQUESTS_CA_BUNDLE` / `CURL_CA_BUNDLE` / `SSL_CERT_FILE`. The admin may set `SMJ_STRICT_CERT=false` to pass `strict_cert=False` to `labapi.Client`; by default strict certificate checking remains enabled. End users only authenticate through their personal LabArchives login; they never see or enter institutional API keys. When the admin has not configured credentials, the user's first sign-in attempt fails with a message directing them to the admin rather than asking them to fix something themselves.

---

## AUTH — Authentication

**C-AUTH-01.** The user authenticates with LabArchives once through a browser-redirect flow initiated by the panel's **Connect** button. A new tab opens at the LabArchives sign-in URL; after completing the form, the tab notifies the main JupyterLab window via `BroadcastChannel` and `localStorage`, displays a "you can close this tab" message, and auto-closes 150 ms later. The panel updates without manual action.

**C-AUTH-02.** Authentication survives Jupyter server restarts. After signing in once, the user's LabArchives session is restored on subsequent Jupyter sessions without re-authentication; the panel shows `Authenticated as <email>.` on first load. Credentials live only in the operating system's secure credential store (Keychain, Credential Manager, Secret Service) — they never appear in the notebook, the repo, or any working-tree file. If no OS credential store is available, the session is in-memory only and the user must re-authenticate after each restart.

**C-AUTH-03.** The panel's auth-row description shows one of exactly four phrasings depending on state: `Authenticated as <email>.` when signed in, `Authentication pending.` while the OAuth flow is in progress, `Not authenticated. Previously connected as <email>.` when signed out (or expired) but a profile remains, and `Not authenticated.` when no profile exists at all.

**C-AUTH-04.** The auth-row button label toggles based on state: `Sign out` when authenticated, `Connect` otherwise. Clicking **Sign out** transitions the status area through `Signing out...` (info) to `Signed out of LabArchives.` (info) on success, or `Unable to sign out of LabArchives.` (error) on failure. Sign-out removes both the in-memory session and the OS-keyring entry for the current profile and any legacy aliases; the next status check shows `Not authenticated.` with no prior-connection hint.

**C-AUTH-05.** Expired LabArchives sessions surface distinctly from other failures. When the next snapshot attempt finds the session expired, the user sees a message beginning `LabArchives session expired; sign in again to continue.` and the panel reverts to the unauthenticated state. Unlike Sign out, expiry does not delete the stored profile, so the panel retains the `Previously connected as <email>.` hint to tell the user which account to reconnect.

**C-AUTH-06.** The OAuth callback page is publicly reachable and presents one of two titles — `LabArchives authentication complete` or `LabArchives authentication failed` — followed by the result message and the line `You can close this tab and return to JupyterLab.`. The page auto-closes after notifying the main JupyterLab tab. If the user closes the auth tab before completing sign-in, the `Authentication pending.` state auto-cancels after 60 seconds and returns the panel to the unauthenticated state with a message inviting another **Connect** attempt; the user can also click **Update panel** or restart the flow sooner.

**C-AUTH-07.** Specific authentication failure causes are surfaced individually rather than as a generic error. Missing server credentials produce the message `LabArchives credentials are not configured for the Jupyter server. Set ACCESS_KEYID and ACCESS_PWD in the server environment before connecting.` TLS bundle misconfiguration produces `The Jupyter server TLS CA bundle is not configured correctly for LabArchives.` followed by guidance about `REQUESTS_CA_BUNDLE` / `CURL_CA_BUNDLE` / `SSL_CERT_FILE`. TLS handshake failures produce `TLS verification failed while connecting to LabArchives.`. Other auth-start or auth-completion failures fall back to `Unable to start the LabArchives authentication flow.` or `LabArchives authentication could not be completed.` respectively.

**C-AUTH-08.** Profiles stored under legacy Jupyter `user_id` formats remain accessible across JupyterLab upgrades. The system tries the current `user_id` first and falls back to known alias representations; the user does not have to re-authenticate after JupyterLab updates the identity scheme.

**C-AUTH-09.** Once authenticated, the panel exposes the list of LabArchives notebooks the user has access to (under `storedNotebookNames`) so target-picker UIs can populate from real data rather than asking the user to type a notebook name.

---

## PANEL — Side Panel Structure

**C-PANEL-01.** The Save My Jupyter side panel attaches to JupyterLab's right sidebar. It is not closable; the user opens it via the command palette (`Open Snapshot Settings`) or by clicking the sidebar tab. The header identifies the extension as `Save My Jupyter`.

**C-PANEL-02.** The panel header exposes a secondary `Update panel` action that refreshes the current notebook-derived review, LabArchives auth state, and recent activity. The primary `Snapshot now` action is visible at the top of the **Snapshot** section. When a snapshot cannot proceed, the primary action is disabled and the panel shows the blocking reason before any configuration controls.

**C-PANEL-03.** The panel body is organized around the snapshot workflow in this order: **Snapshot**, **What will be saved**, **Tracked files**, **Triggers**, **Snapshot options**, **Connection & config**, and **Activity**. The top **Snapshot** section still shows whether the current notebook can be saved before the user reaches configuration controls; **Connection & config** carries the readiness details and setup actions.

**C-PANEL-04.** The workflow-first panel summarizes the active notebook path, LabArchives connection state, LabArchives destination, git or repository state, and every blocking issue that prevents snapshotting. LabArchives connection controls and project-config controls live in **Connection & config**, including connect, sign out, starter-config creation, and starter-config existence checks. With no notebook open, it tells the user to open a notebook before configuring or saving snapshots. For notebooks outside any git repo, the git state explicitly says no repository was detected.

**C-PANEL-05.** A persistent output-upload disclosure appears before the user can create a snapshot. It states that snapshots upload the full notebook with outputs, including stdout, stderr, rendered data, and embedded figures, and warns the user to clear sensitive outputs before saving. The disclosure has `role="note"` and is not dismissible.

**C-PANEL-06.** The **What will be saved** section presents a snapshot review generated from the same backend-resolved policy and plan that snapshot execution will use. The review includes the target LabArchives notebook and path, notebook-file inclusion, output and figure inclusion, tracked-file matches or tracked-file rules, git commit or diff behavior, trigger policy, and metadata summary. The panel does not independently reimplement policy merging to produce this review.

**C-PANEL-07.** The **Snapshot options** section contains controls for user-editable and notebook-editable snapshot inputs: commit mode, trigger mode, trigger-cell state for the active cell, tracked files, tags, run label, notes, and any supported metadata fields. Changing an option refreshes the snapshot review so the user can see the effective result before saving.

**C-PANEL-08.** Setup actions live inside **Connection & config**. Each setup action exposes its own success, warning, or error state without replacing the current snapshot activity.

**C-PANEL-09.** The **Activity** section shows the current snapshot job when one is running or queued, including phase-level progress such as saving, capturing, committing, and uploading. After completion, the most recent successful receipt remains visible until replaced or dismissed, and recent failures remain inspectable with their specific error messages. Failed Activity rows expose backend error details when available: the specific error message is shown under the row, and the error code is shown as diagnostic context rather than hidden behind the compact toast. When the current snapshot status is an error, the top **Snapshot** section also shows the latest failure details so the user does not have to scroll or guess where the full error lives.

**C-PANEL-10.** Status messages render with one of four visual kinds — `info`, `success`, `warning`, `error` — and are announced through an `aria-live="polite"` region. Empty, unavailable, and blocked values are rendered explicitly rather than as blank space.

---

## TOOLBAR — Notebook Surface

**C-TOOLBAR-01.** Save My Jupyter does not add manual snapshot actions to the native notebook toolbar. Manual snapshots are started from the panel's primary action or the command palette, keeping the notebook toolbar focused on notebook editing and execution controls.

**C-TOOLBAR-02.** Cells marked as triggers receive a visible left-edge accent decoration in the brand color. The decoration persists across scrolling and across cell reordering and travels with the notebook file.

---

## COMMANDS — Palette & Context Menu

**C-CMD-01.** The command palette under category `Save My Jupyter` exposes commands to start a manual snapshot, open the side panel, toggle the selected cell's trigger state, explicitly mark or unmark the selected cell as a trigger, and toggle all-cells trigger mode. Each command is invokable with no panel open and produces the same behavior as the equivalent panel control.

**C-CMD-02.** Right-clicking a cell shows a contextual trigger-toggle entry. The label adapts to state: `Mark Cell As Trigger` when the cell is not marked, `Unmark Cell As Trigger` when it is, or `Toggle Cell Trigger` when the cell cannot be identified from the click position.

**C-CMD-03.** Changing the all-cells-trigger setting from any surface produces a confirming panel/status message: `Every executed cell will trigger snapshots.` when enabled, or `Only marked trigger cells will create automatic snapshots.` when disabled. Attempting to mark a trigger cell without any cell selected produces the panel/status warning `Select a cell before changing trigger status.`. These trigger-control messages are not JupyterLab toast notifications; marked cells are visually confirmed by the notebook cell trigger accent.

---

## SNAP — Manual & Trigger-Cell Snapshots

**C-SNAP-01.** Manual snapshots can be fired from two equivalent surfaces: the panel's Snapshot button and the command palette's `Snapshot Now`. Both converge on identical behavior — same target, same artifacts, same status. Two manual clicks in quick succession always produce two snapshots; manual snapshots are never deduplicated against each other.

**C-SNAP-02.** Manual snapshots while unauthenticated are blocked without submitting a snapshot request. The Save My Jupyter panel is opened, its status shows `Connect LabArchives before creating a snapshot.`, and its Readiness section shows the same blocker. No modal dialog or toast notification is shown for this normal blocked-action path.

**C-SNAP-03.** Before a manual snapshot fires, the notebook is saved to disk via `panel.context.save()`. If save fails (read-only filesystem, permission issue), the manual snapshot does not proceed and the user sees the JupyterLab save error in its usual location. Automatic trigger snapshots also save the notebook before submitting, but only after the trigger candidate has settled under C-SNAP-08; they never save on each executed trigger cell. If that settled trigger save fails, the trigger snapshot does not proceed.

**C-SNAP-04.** During a manual snapshot, the panel Activity section shows the info message `Saving notebook, creating snapshot artifacts, and uploading to LabArchives.` until the snapshot completes. The status only transitions to "saved" or "failed" after persistence to LabArchives has finished; "saved" is never shown before the data is actually in LabArchives.

**C-SNAP-05.** A successful snapshot's status begins with `Snapshot saved.` followed by space-separated reference clauses, each ending with a period. Possible clauses, in order: `Job <jobId>.`, `Snapshot <snapshotId>.`, `Commit <short-hash> created.` for a new commit or `Existing HEAD <short-hash> reused.` when no new commit, `Commit URL: <url>.` when a URL can be built, and `LabArchives <url>.` — the clickable snapshot-directory URL (C-DEST-05) — falling back to `LabArchives page <name-or-id>.` when no directory URL can be built. Short commit hashes are the first 12 characters when the full hash exceeds that length. Clauses without data are omitted, not rendered as "unknown." Successful manual snapshots update the panel status and Activity history without a toast notification; successful trigger snapshots also update the panel status and Activity history, and may show the compact confirmation defined in C-SNAP-07.

**C-SNAP-06.** A failed manual snapshot falls back to the message `Unable to save the snapshot.` in the panel Activity section when no more specific message is available. Trigger snapshot failures fall back to `Save My Jupyter trigger snapshot failed.`.

**C-SNAP-07.** Trigger-cell snapshots fire automatically when a run includes a cell that is marked as a trigger (or notebook-level all-cells-trigger mode is on). A run that ends in an error still produces a snapshot if a trigger cell ran — the error state (traceback, partial outputs) is captured, not discarded — and the snapshot records `run_outcome = error` on its Activity receipt; successful runs record `run_outcome = success`. The triggering signal carries per-cell success, which is recorded but never used to suppress the snapshot. Automatic trigger snapshots do not show start toast notifications. A successful trigger snapshot may show one compact success toast with the generic body `Snapshot saved.` and auto-close after 1 second; details remain in Activity. A failed trigger snapshot may show one compact error toast with the generic body `Save My Jupyter trigger snapshot failed.` and auto-close after 4 seconds; details remain in Activity.

**C-SNAP-08.** A single run resolves to at most one automatic trigger snapshot, regardless of how many trigger cells it executes or how long it takes. As each cell finishes, triggered cells accumulate into a per-notebook pending set (filtered only on trigger membership, never on success). When the run completes — signalled once per Run All / Run Selected / single Shift+Enter, and emitted on both success and error — the pending set becomes one trigger-snapshot candidate whose triggered cell set is the union of all cells in the run and whose representative triggering cell is the run's last cell. Trigger-snapshot candidates remain queued until the system has evidence that execution has settled: either the representative triggering cell is the notebook's final non-empty cell, ignoring blank tail cells that Jupyter may create during run-and-step, or a 5-second quiet window expires. Adjacent single-cell execution commands before either condition merge into one candidate. Once settled, the frontend resolves trigger metadata and compares normalized notebook content; if the content changed from the last submitted trigger candidate for that notebook, it saves the notebook once and submits the candidate. The normalized notebook content includes every notebook cell's content, including source code and output payloads, plus the resolved tag set, while ignoring execution-count, cell-id, and metadata noise. Changing any cell content, any output, or tags is enough to create a new automatic snapshot; repeating the same notebook content and tags is skipped. Manual `Snapshot Now` submissions bypass this debounce entirely. Backend run-fingerprint dedupe (TTL-bounded, keyed on the run) remains as defense-in-depth against overlapping submissions (trigger plus manual, restart races, multiple tabs); if a run completes without its end signal (an execution path that bypasses the notebook actions), a kernel-idle transition with a non-empty pending set flushes a trigger-snapshot candidate into the same settle queue instead.

**C-SNAP-09.** Trigger configuration travels with the notebook file. Cell trigger marks live under `cell.metadata.save_my_jupyter.trigger`, and notebook-level state lives under `notebook.metadata.save_my_jupyter` (including `trigger_cell_ids` and `all_cells_trigger`). A teammate opening the same `.ipynb` with the extension installed inherits the same trigger setup with no extra configuration.

---

## WATCH — Tracked Files

**C-WATCH-01.** Tracked files are configured through the panel's Tracked files form: the user types a relative path or glob, clicks `Add`, and sees it appear in the list with a `Remove` button. Successful registration produces the success status `Tracking <normalized-path>.` and removal produces the info status `Stopped tracking <path>.`. The list persists with the notebook file.

**C-WATCH-02.** Tracked path entries are validated before they are persisted. Empty or whitespace-only input is rejected with `Tracked paths must not be empty.`. Paths starting with `/`, `\\`, or matching a Windows drive prefix (`C:\` etc.) are rejected with `Tracked paths must be relative.`. Any `..` segment is rejected with `Tracked paths must stay within the notebook or repo root.`. Paths consisting only of `.` segments are rejected with `Tracked paths must include at least one path segment.`. Accepted paths are stored in POSIX form (forward slashes, `.` and empty segments collapsed).

**C-WATCH-03.** Tracked paths support glob patterns. Any path containing `*`, `?`, or `[` is treated as a glob; patterns like `**/*.py` match files at any depth. Non-glob paths match a literal file or directory.

**C-WATCH-04.** Tracked paths are gathered at snapshot time, not polled. A snapshot includes whichever matching files exist on disk at the moment the snapshot fires. The system never watches the filesystem or fires snapshots in response to file changes; a file created and deleted between two snapshots is never captured.

**C-WATCH-05.** Tracked-path resolution silently drops files that fall outside the project tree (the configured root being the git repo root when available, otherwise the notebook's parent directory). When a tracked glob would otherwise pull in a file via a symlink pointing outside the project, the resolved path is checked again after `.resolve()` and dropped if it escapes. Each dropped file produces a server-side warning log so operators can audit what was excluded.

**C-WATCH-06.** Tracked-path resolution silently drops files matching common credential filenames — `.env`, `.env.*`, `*.pem`, `*.key`, `id_rsa*`, `id_ed25519*`, `id_ecdsa*`, `.netrc`, `.htpasswd`, `*.p12`, `*.pfx`, `credentials`, `credentials.json` — and files under credential-bearing parent directories `.ssh/` and `.aws/`. Matching is case-insensitive on Windows and case-sensitive on POSIX. The exclusion is automatic and requires no user opt-in; the server logs a warning per skipped file.

**C-WATCH-07.** Tracked-path resolution silently drops files under common build, cache, and virtual-environment directories: `.git`, `.ipynb_checkpoints`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.tox`, `.uv-cache`, `.venv`, `__pycache__`, `env`, `node_modules`, `venv`. These exclusions are automatic.

**C-WATCH-08.** Tracked files larger than 25 MiB each cause the snapshot to fail before any LabArchives call, with a clear "too large" error naming the offending file. Tracked files that cannot be read (permission errors, etc.) raise a distinct read-failure error carrying the path.

---

## CONFIG — Configuration

**C-CONFIG-01.** The effective configuration for any snapshot is computed by merging five layers in fixed precedence, highest first: the snapshot request itself (e.g., the commit mode chosen in the panel for this snapshot), the notebook's own metadata at `notebook.metadata.save_my_jupyter`, the user's JupyterLab settings under plugin id `@save-my-jupyter/extension:plugin`, the repo's `.save-my-jupyter.toml`, and a deterministic inference layer. A value unset at all five layers falls back to a built-in hardcoded default. The inference layer is where the system supplies sensible context-derived values (target path, run label) so a user who configures nothing still gets a working, non-arbitrary result.

**C-CONFIG-02.** The panel's snapshot review reflects the merged policy the next snapshot will use, computed by the backend from the same resolver and matching logic that execution uses. The review is **advisory and timestamped**: it shows the plan as of the moment it was computed, from either the saved notebook on disk or frontend-supplied in-memory notebook content (the review states which). When the panel knows the notebook has unsaved changes not reflected in the review, it marks the review stale or pending refresh rather than silently showing disk state. Filesystem-dependent parts of the plan (tracked-file matches in particular) are recomputed at snapshot execution time, so the **Activity receipt is authoritative** for what was actually uploaded. When the resolved state cannot be computed, the panel shows the blocker or unavailable state explicitly rather than rendering blank values.

**C-CONFIG-03.** The repo config file lives at `.save-my-jupyter.toml`. It is discovered by walking up from the notebook directory until the system finds `pyproject.toml`, `package.json`, or `.git`. Supported top-level sections are `[project]`, `[defaults]`, `[labarchives]`, and `[git]`; unknown sections and keys are ignored.

**C-CONFIG-04.** Repo config field defaults and shapes: `[project]` accepts `name: string` (defaults to the discovered directory name or `save-my-jupyter`) and `repo_root_strategy: "git" | "fixed"` (default `git`); other values for `repo_root_strategy` raise a validation error at parse time. `[defaults]` accepts `all_cells_trigger: bool` (false), `commit_mode: "ask" | "always" | "never"` (`ask`; legacy value `prompt` is accepted as an alias for `ask` for one release), `watch_paths: string[]` (tracked files; default empty), `metadata: map[string, string]` (empty; commonly written as `[defaults.metadata]`), `include_notebook_file: bool` (true), `include_diff_when_dirty: bool` (true). `[labarchives]` accepts optional `target_notebook: string` and `target_root_path: string`. `[git]` accepts `stage_notebook_on_commit: bool` (true), `stage_watched_paths_on_commit: bool` (true), and `commit_message_template: string` (`snapshot: {notebook_name} {timestamp}`). A file that cannot be parsed as TOML raises a parse error carrying the file path; the snapshot falls back to higher-layer values only.

**C-CONFIG-05.** Notebook-local overrides live under `notebook.metadata.save_my_jupyter`. Supported keys are `enabled` (default true), `all_cells_trigger` (false), `trigger_cell_ids` (empty array), `watched_paths` (empty array), `labarchives_target_notebook` (nullable), `labarchives_target_root_path` (nullable), and `default_metadata` (empty map). These persist with the `.ipynb` file and travel with it through git, sharing, and copy operations.

**C-CONFIG-06.** Trigger marks on individual cells live under `cell.metadata.save_my_jupyter.trigger`, a boolean. The notebook-level `trigger_cell_ids` is a denormalized view of which cells are currently marked.

**C-CONFIG-07.** User preferences live in the JupyterLab settings registry under plugin id `@save-my-jupyter/extension:plugin`. Supported keys are `defaultCommitMode` (`ask | always | never`; unset means no stored preference, which leaves the effective mode at `ask`), `defaultRunLabel` (nullable), `defaultTags` (empty array), and `rememberCommitChoice` (default false). When the user picks a commit mode in the `ask` prompt and checks "remember this decision," the chosen mode is written to `defaultCommitMode` and `rememberCommitChoice` is set, suppressing future prompts. Older keys removed from the schema — notably `defaultExperimentContext` — are silently dropped at parse time rather than rejected, so users upgrading don't lose access to their settings.

**C-CONFIG-08.** With nothing configured anywhere, the system falls back to documented defaults. Target LabArchives notebook is `Jupyter Snapshots`. Target root path is **inferred** as `Notebook Log/{user_email}/{project_name}/{relative_notebook_path}`. The `{user_email}` segment is intentional: the common deployment shares one LabArchives notebook across a team, so scoping each contributor's snapshots under their authenticated email keeps them from colliding. Commit mode is `ask`. Tracked paths default to empty (tracked files are opt-in, not a `**/*.py` default). The notebook file is included; the dirty diff is included; the notebook is staged on commit; tracked paths are staged on commit by default once configured; the commit message template is `snapshot: {notebook_name} {timestamp}`; the project name is `save-my-jupyter`.

**C-CONFIG-09.** Clicking **Create starter config** in the panel writes a working `.save-my-jupyter.toml` at the resolved project root, including explanatory comments and all common settings filled in. The default `target_root_path` in the generated file is `Notebook Log/{user_email}/{project_name}/{relative_notebook_path}`, matching the inferred default (C-CONFIG-08) so zero-config and starter-config land snapshots in the same place. On success the status reads `Created starter config at <path>.` (success). When a file already exists, the Readiness section says `This config is already available for the current notebook.` and does not expose a create/regenerate button. Without a notebook open the row shows `Open a notebook before creating a repo config.` (warning). A file-write failure shows `Unable to create the starter config.` (error). A secondary hint below the row reads either `This config is already available for the current notebook.` (when loaded) or `Create a starter .save-my-jupyter.toml to share defaults for this workspace.` (with the filename rendered as code).

**C-CONFIG-10.** The preview path (which feeds the panel) and the snapshot path (which creates a snapshot) both load the notebook's `metadata.save_my_jupyter` and feed it into the same five-layer merge. The user can rely on the panel's resolved view matching what the snapshot will do; the two paths share one resolver.

**C-CONFIG-11.** Every field in the resolved configuration carries provenance: which layer it came from (`request`, `notebook`, `user`, `repo`, `inferred`, or `fallback`). Fields whose value came from the inference layer are labelled `(inferred)` inline in the "What will be saved" review, so a user can tell a value the system supplied from one they set. The label is shown inline next to the value, not hidden behind hover, for any field that affects where data lands (destination) or how a run is identified (run label, commit mode).

---

## TEMPLATE — LabArchives Path Templates

**C-TEMPLATE-01.** The LabArchives `target_root_path` may contain placeholder variables that are substituted at snapshot time. The supported set is fixed: `{name}` and `{project_name}` (project name from repo config, falling back to `save-my-jupyter`); `{user_id}` (the Jupyter user id); `{user_email}` (the authenticated LabArchives email, falling back to `unknown-email`); `{repo_name}` (the repo root's directory name, falling back to `no-repo`); `{notebook_name}` (the notebook filename); `{notebook_stem}` (the notebook filename without `.ipynb`); `{relative_notebook_path}` (the notebook's path relative to the repo root, falling back to the notebook name); `{scope_path}` (alias for `{relative_notebook_path}`); `{scope_name}` (the last segment of `{scope_path}`); `{run_label}` (the user-entered run label, falling back to `unlabeled`); `{experiment_context}` (a legacy variable retained for back-compat — no longer an editable field, always renders `no-context`); `{timestamp}` (ISO-8601 seconds with `:` replaced by `-`); `{date}` (`%Y-%m-%d`); `{time}` (`%H-%M-%S`); `{source}` (`manual` or `trigger_cell`); `{commit_hash}` (the commit hash, falling back to `dirty`). Removing or renaming any of these is a breaking change.

**C-TEMPLATE-02.** A template referencing a variable not in the catalog raises a distinct error naming the variable, before any LabArchives call. A template that renders to nothing after segment stripping raises an empty-target-path error. Both errors are surfaced to the user with the offending template included.

**C-TEMPLATE-03.** Path templates cannot escape their target directory. Each rendered path segment is sanitized: a segment equal to `..` raises a distinct unsafe-segment error; segments containing colons or matching a Windows drive-letter pattern (`C:` etc.) raise the same error; segments containing control characters raise the same error. Trailing dots are stripped, `.` segments and empty segments are dropped silently. The error message carries both the template and the offending raw segment. A failure here prevents the snapshot from proceeding at all; nothing is written to LabArchives with an unsafe path.

---

## GIT — Git Integration

**C-GIT-01.** Git context is detected automatically. The system walks upward from the notebook's directory looking for `.git`; if found, the panel's readiness or snapshot-review surface shows the repo root, HEAD commit, dirty state, and remote URL. When the notebook is outside any git repo, the panel explicitly says no repository was detected and snapshots still proceed — the git-context fields are simply absent.

**C-GIT-02.** Three commit modes are supported: `ask`, `always`, and `never`, resolved through the standard five-layer merge (request, notebook, user, repo). When the effective mode is `ask` at snapshot time, the panel shows an in-panel commit prompt offering `always` / `never` for this snapshot plus a "remember this decision" checkbox; checking it persists the chosen mode to the user's `defaultCommitMode` so the prompt stops recurring. `ask` is the default for new installs and the migration path for existing users who never set a commit mode — a stored `defaultCommitMode` suppresses the prompt entirely. Legacy `prompt` configuration values are treated as `ask` for one release.

**C-GIT-03.** Snapshot commits stage only what was asked for. With `stage_notebook_on_commit = true` (the default) the notebook file is staged; with `stage_watched_paths_on_commit = true` (the default) the configured tracked paths are also staged; the `.save-my-jupyter.toml` file is also staged when modified. Unrelated working-tree changes are never staged, never committed, and never pushed. A staging failure (gitignored target, permission error) raises a distinct error with the underlying message and prevents the snapshot from proceeding.

**C-GIT-04.** The dirty diff included in a snapshot is scoped to the notebook and configured tracked paths. Unrelated edits elsewhere in the working tree never appear in the snapshot's diff. Tracked files that are not already tracked by Git appear in the diff as added files. A diff-generation failure raises a distinct error and prevents the snapshot from proceeding.

**C-GIT-05.** Commits succeeding but with an unreadable HEAD afterward raise a distinct error rather than reporting success with a missing hash. Commit creation failures (merge conflict, hook rejection, etc.) raise a distinct error carrying the underlying message.

**C-GIT-06.** Snapshots distinguish a freshly-created commit from a reused HEAD. The success status phrases this explicitly as `Commit <hash> created.` versus `Existing HEAD <hash> reused.`. The same hash can appear in both cases; the boolean is the differentiator.

**C-GIT-07.** Commit URLs are built automatically for recognized hosts. A remote URL containing `github.com` produces `<base>/commit/<hash>`; one containing `gitlab` produces `<base>/-/commit/<hash>`; one containing `bitbucket` produces `<base>/commits/<hash>`. SSH-form remotes (`git@host:owner/repo`) are rewritten to HTTPS first; `.git` suffixes are stripped. Hosts outside that set produce no URL — the hash alone is still surfaced. Commit-hash strings are validated against `^[0-9a-f]{7,40}$` before use.

**C-GIT-08.** Commit messages follow a template with `{notebook_name}` and `{timestamp}` substitutions; the default is `snapshot: {notebook_name} {timestamp}`. Template editing is per-repo via `[git] commit_message_template`.

---

## CONTENT — What Snapshots Contain

**C-CONTENT-01.** A snapshot uploads the notebook file in its entirety when `include_notebook_file` is true (the default). The upload includes all cell sources, all outputs (stdout, stderr, rendered data, tracebacks), all embedded base64 data, and all notebook metadata. Notebooks larger than 50 MiB cause the snapshot to fail before any LabArchives call, with a "notebook too large" error.

**C-CONTENT-02.** The user is told that outputs are uploaded. A persistent paragraph in the side panel and matching language in `docs/usage.md` explain that the notebook is uploaded with all output content. There is no automatic redaction; the user is responsible for clearing sensitive outputs before snapshotting.

**C-CONTENT-03.** PNG, JPEG, and SVG images embedded in cell outputs are rendered inline in the readable notebook page when the notebook file is included. They are only extracted as standalone figure artifacts when `include_notebook_file` is false; standalone figures are numbered in the order they appear, named `figure-001.png` (or `.jpg`, `.svg`).

**C-CONTENT-04.** Tracked files matched at snapshot time are uploaded as separate attachments. MIME type is determined by extension: `.csv` → `text/csv`, `.json` → `application/json`, `.svg` → `image/svg+xml`, `.tsv` → `text/tab-separated-values`, `.txt` → `text/plain`; otherwise Python's `mimetypes.guess_type()` is consulted, falling back to `application/octet-stream`. The notebook file itself uses `application/x-ipynb+json`.

**C-CONTENT-05.** When the repo is dirty and no new commit was created for the snapshot, the working-tree diff is included as an artifact when `include_diff_when_dirty` is true. The diff is scoped to the notebook and configured tracked paths and is rendered in a readable form on the LabArchives metadata page. Raw diff attachments are truncated at roughly 1 MB; the truncation is visible in the diff itself. The diff's description carries the explicit qualifier `Filtered working tree patch; notebook JSON and image patches are omitted`.

**C-CONTENT-06.** A rich notebook diff is rendered cell-by-cell against the pre-snapshot HEAD when one is available, omitting noise like `execution_count` fluctuations, metadata churn, and base64 output changes. When the notebook file is included, the diff is merged into that notebook's readable HTML page instead of being saved as a separate notebook-diff page; when the notebook file is not included, the rich diff remains a standalone page so the diff information is not lost. Raw working-tree patches separately drop sections corresponding to image files (`.png`, `.jpeg`, `.gif`, `.svg`, `.bmp`, `.tif`, `.tiff`, `.webp`, `.avif`) when the rich notebook diff already represents those changes.

**C-CONTENT-07.** Each snapshot includes a short text summary of the last meaningful execution output, truncated at 5,000 characters. When no output text is available, the summary reads `(no execution summary available)`.

**C-CONTENT-08.** User-entered metadata is round-tripped to the LabArchives metadata page exactly as entered: tags (deduplicated, whitespace-trimmed), notes (multiline), and run label. Tags from all sources — UI-entered tags, repo-config `default_tags`, in-source code directives (see DIRECTIVE family), and Python-kernel `smj_tags` values — are merged by union, order-insensitive and de-duplicated.

---

## DIRECTIVE — Code-Defined Tags & Run Label

**C-DIRECTIVE-01.** The user can declare tags and a run label directly in notebook source via an inert comment directive: a comment line whose body starts with `smj:` (case-insensitive), followed by `;`-separated `key=value` pairs. Recognized keys are `tags` (comma-separated) and `run` (free text). Example: `# smj: run=training-3; tags=baseline, gpu`. The directive is parsed statically and never executed, so it requires no kernel package, no import, and no IPython hook — consistent with kernel independence.

**C-DIRECTIVE-02.** Directives are scoped to the whole notebook; every cell is scanned. Tags from all `tags=` directives merge by union with UI tags and config defaults. The run label comes from the first `run=` directive in notebook order; if none exists, a trigger snapshot falls back to the first non-blank line of the triggering cell, and a manual snapshot leaves the run-label field editable (pre-filled from a directive when one is present). Parsing reads in-memory cell source at submission so unsaved edits are honored, with a backend disk parser as the fallback for server-side paths; the two parsers share a fixture suite to guarantee identical behavior.

**C-DIRECTIVE-03.** Run-label timing differs by snapshot kind. Manual snapshots expose an editable run-label field (and tags) before submission, pre-filled from any directive, so the user can adjust them. Trigger snapshots infer the run label at submission time (directive first, then triggering-cell fallback) and do not pause for the user to edit it, since trigger snapshots fire as the run completes.

**C-DIRECTIVE-04.** Python notebooks can define live dynamic metadata through `smj_tags` and `smj_run`. If missing, the snapshot path initializes `smj_tags = []` and `smj_run = None` in the kernel before reading them. `smj_tags` may be a single tag value or an iterable of tag values; strings are trimmed, numbers and booleans are stringified, blanks and unsupported values are ignored. `smj_run` may be a non-blank string. For manual snapshots, an explicitly edited panel run label wins; otherwise `smj_run` wins over directive/default run labels. For trigger snapshots, `smj_run` wins over directive and triggering-cell fallback labels. Dynamic values are read at snapshot submission time and are not persisted into notebook metadata.

---

## DEST — Where Snapshots Land in LabArchives

**C-DEST-01.** Each snapshot creates one new directory in the configured LabArchives notebook, under the rendered target root path. The directory name is built as `<iso-millisecond-timestamp>_<short-snapshot-id>` and is guaranteed unique — back-to-back snapshots within the same millisecond still receive distinct directory names because the snapshot-id suffix is fresh per record. Names use the existing-page `Raise` insert behavior, so a name collision fails the snapshot rather than overwriting.

**C-DEST-02.** Every snapshot directory contains a canonical page named exactly `00 Metadata` (sorting first alphabetically). It carries a table of snapshot metadata — Notebook, Notebook path, Source, Run outcome (success/error), Snapshot ID, Run fingerprint, Trigger cells, Commit hash, Commit status, Commit URL, Diff included (Yes/No), Extension version, Run label, Tags (labeled `Tags (metadata text, not native LabArchives tags)`), Notes — plus an Artifacts index linking to the other pages in the directory.

**C-DEST-03.** Beyond the metadata page, each notebook attachment lives on its own LabArchives page with a readable cell-by-cell HTML rendering of the notebook, including all captured outputs and inline image outputs, plus the raw `.ipynb` attachment. When a rich notebook diff is available, that same notebook page displays the diff-enhanced cell view rather than creating a second notebook-diff page. Each tracked file lives on its own page. Page names use the file's basename truncated at 120 characters.

**C-DEST-04.** Snapshot delivery is atomic from the user's perspective. If any part of the LabArchives write fails — directory creation, individual pages, attachment population — the system attempts to move every page and directory it created to LabArchives's `API Deleted Items` tree before reporting the failure to the user. The cleanup is best effort; if cleanup itself fails, the original error is still reported and the orphaned items remain in LabArchives until the user removes them manually.

**C-DEST-05.** A successful snapshot's response carries every reference the user might need to find the result: the snapshot id, the LabArchives directory name, the metadata page's id and name, the total page count, and a clickable LabArchives URL to the snapshot directory. The clickable URL appears in the panel Activity receipt and snapshot status, not just as a page name the user must search for.

**C-DEST-06.** The default LabArchives destination is `Notebook Log/{user_email}/{project_name}/{relative_notebook_path}`: a `Notebook Log` root, then the authenticated user's email, then the project name, then the notebook's repo-relative path. The email segment is deliberate — the common deployment shares one LabArchives notebook across a team, and scoping by email prevents contributors' snapshots from colliding. (This is an intentional reversal of the earlier no-PII-in-default-path stance, made because shared notebooks are the norm here.) A user writing to a personal, unshared notebook can drop the email segment by editing `target_root_path`.

---

## QUEUE — Per-Notebook Queue Behavior

**C-QUEUE-01.** Snapshots are queued per notebook, keyed by document id (or notebook path when document id is unavailable). Notebooks queue independently — work on one notebook never blocks or dedupes against another. Each notebook accepts at most five pending snapshots; the sixth submission is rejected with `reasonCode = "snapshot_queue_full"` and the message `Too many snapshots are already queued for this notebook. Wait for the current save to finish before starting another.`.

**C-QUEUE-02.** Manual snapshots never dedupe — each click is its own submission. Trigger snapshots dedupe by run fingerprint, which includes the normalized tag set: a submission whose fingerprint matches a currently running or pending job collapses into the existing job (returning success without enqueueing), and a submission whose fingerprint matches a completed job is rejected with `reasonCode = "duplicate_run"` and the message `A snapshot already exists for this run.`. Adding or removing a tag changes the fingerprint so a researcher can add tags after a run and submit a new trigger snapshot without changing executable notebook code. Each successful submission receives a fresh job id, including coalesced ones, so clients can correlate per request.

**C-QUEUE-03.** Unauthenticated snapshot submissions are rejected immediately with `reasonCode = "authentication_required"` and the message `Connect LabArchives before creating a snapshot.`. No queue entry is created.

**C-QUEUE-04.** Snapshots that fail during execution or persistence do not record their run fingerprint, so the user can retry the same trigger event without hitting a `duplicate_run` rejection. The queue itself unsticks: the next manual or trigger snapshot for the same notebook proceeds normally without server restart.

**C-QUEUE-05.** A snapshot job moves through the states `queued`, `running`, `persisted`, `failed`, and `abandoned`. `abandoned` is set on Jupyter startup for any job that was `queued` or `running` when the server last stopped — a restart never leaves a job appearing to run forever. The delivery state (`persisted`/`failed`) is distinct from the run outcome (`run_outcome = success | error | n/a`): a snapshot of an errored run is `persisted` with `run_outcome = error`.

**C-QUEUE-06.** Activity history is durable across restarts; deduplication state is not. The Activity store records each job's submitted/completed timestamps, source, notebook path, state, run outcome, snapshot id, commit hash and URL, LabArchives directory and metadata-page references, page count, error code, error message, and the canonical display message. It never stores auth tokens, notebook contents, tracked-file contents, tags, run labels, notes, or diffs. Notebook paths are stored repo-relative when a repo root is known (Jupyter-server-relative, then absolute, as fallbacks) to limit path-based information exposure. The run-fingerprint dedupe cache, by contrast, is in-memory with a short TTL and resets on restart, so a restart is a reliable way to re-run a previously-deduped snapshot; a manual snapshot is the always-available force-override.

---

## API — User-Visible HTTP Surface

**C-API-01.** All HTTP endpoints live under `<jupyter_base_url>/save-my-jupyter/`. Every endpoint except the OAuth callback requires Jupyter's `@web.authenticated`; unauthenticated requests are rejected by Jupyter before reaching the handler. The OAuth callback at `/auth/callback/<request_id>` is the only externally-reachable endpoint and is the public side of the LabArchives sign-in flow.

**C-API-02.** Errors are returned as JSON with the shape `{"error": {"code": "<code>", "message": "<text>", "context": {...}}}`. The `code` is a stable namespaced identifier; the `message` is meant to be shown to humans; the `context` carries case-specific structured data (paths, segments, fields). Frontends and external integrations can key recovery behavior off `code` without parsing the message.

**C-API-03.** The OAuth callback accepts either `?email=<email>&auth_code=<code>` on success or `?error=<message>` on failure as URL query parameters; the `request_id` is the URL path segment. A callback for an unknown `request_id` produces a distinct error rather than silently doing nothing.

**C-API-04.** Snapshot creation is asynchronous from the client's view. `POST /snapshot` returns immediately with camelCase fields such as `{jobId, status}` (`accepted` or `rejected` with a `reasonCode`) once the request enters the queue; it does not block on the upload. The client follows progress via `GET /snapshot-jobs/<id>` (current state and references) and reads recent history via `GET /snapshot-jobs?limit=N`. The "What will be saved" review is served by `POST /snapshot-preview` (body carries in-memory notebook content) or `GET /snapshot-preview?notebook_path=...` (disk-only fallback, marked as such). Tracked paths travel in the snapshot request body using the legacy `watchedPaths` field; `POST /watch/sync` returns HTTP 410 Gone with a JSON error envelope.

---

## FAIL — Failure Vocabulary

**C-FAIL-01.** The system surfaces specific error codes for each failure class rather than collapsing failures into a generic message. The catalog includes: payload validation errors (`invalid_<type>`, `invalid_sequence`, `invalid_sequence_item`, `invalid_datetime`, `absolute_path_not_allowed`, `path_escapes_root`, `invalid_commit_mode`, `invalid_snapshot_source`, `missing_triggering_cell`, `missing_json_body`); repo-config errors (`repo_config_parse_failed`, `invalid_repo_root_strategy`); path-template errors (`unknown_labarchives_target_path_variable`, `empty_labarchives_target_path`, `unsafe_labarchives_target_path`); artifact errors (`notebook_artifact_too_large`, `watched_file_artifact_too_large`, `watched_file_artifact_read_failed`, `artifact_size_check_failed`, `notebook_artifact_parse_failed`); git errors (`git_stage_failed`, `git_commit_failed`, `git_commit_missing_head`, `git_diff_failed`); LabArchives write errors (`labarchives_write_failed`, `labarchives_session_expired`, `unsupported_artifact`, `missing_notebook_payload`); and auth errors (`labarchives_auth_start_failed`, `labarchives_authentication_failed`, `missing_labarchives_credentials`, `invalid_tls_ca_bundle`, `labarchives_tls_verification_failed`, `missing_labarchives_session`, `missing_auth_request`). Adding new codes is a routine evolution; renaming existing ones is a breaking change for consumers that key off codes.

**C-FAIL-02.** Snapshot submissions that are rejected at queue-time produce a `reasonCode` from a small fixed set: `authentication_required`, `duplicate_run`, or `snapshot_queue_full`. Each carries a fixed human message (see C-QUEUE-01 through C-QUEUE-03 and C-SNAP-02).

**C-FAIL-03.** Every handler-caught error is logged once at WARNING level on the server with the shape `Save My Jupyter request failed: method=<m> uri=<u> status=<s> code=<c> message=<msg> context=<json>`. Operators can find what went wrong without instrumenting the client.

---

## STATE — Persistence & Lifecycle

**C-STATE-01.** Authentication, notebook trigger marks, tracked-path lists, user preferences, repo config, and Activity history all survive Jupyter server restarts — they live in the OS keyring, the notebook file, the JupyterLab settings registry, the repo, and a durable Activity store respectively. Currently-pending queue entries, in-flight jobs (marked `abandoned`), and the dedupe cache are lost on restart; persisted content in LabArchives is unaffected.

**C-STATE-02.** The extension assumes a single user per Jupyter server. Multi-user concurrent operation on one server is not tested and the queue does not isolate per-user.

---

## OUT OF SCOPE

The current implementation does **not** promise the following. A rewrite may add any of these; the current code does not and the docs must not claim them.

- **OS-01.** Event-driven snapshots on tracked-file changes. Tracked paths are gathered at snapshot time only (C-WATCH-04).
- **OS-02.** Durable retry queue for failed LabArchives writes (C-STATE-01).
- **OS-03.** Native LabArchives tag fields. Tags appear in rich-text metadata, not in LabArchives's tag taxonomy (C-DEST-02 explicit qualifier).
- **OS-04.** Automatic redaction of sensitive notebook outputs. Disclosure only (C-CONTENT-02).
- **OS-05.** AI-assisted summarization, tagging, or post-processing.
- **OS-06.** Kernel-specific enrichment beyond the Python `smj_tags` and `smj_run` dynamic-metadata exception, such as arbitrary live variable capture or `pip list`.
- **OS-07.** Multi-user concurrent operation on one Jupyter server (C-STATE-02).
- **OS-08.** Offline or queued-for-later mode. If LabArchives is unreachable, the snapshot fails immediately.
- **OS-09.** Per-file opt-in within a snapshot. All tracked files matched at snapshot time are attached.
- **OS-10.** Editing the user-entered metadata (tags, run label, notes) on a snapshot after creation.
