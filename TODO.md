Priority ID TODO Stakeholder aim served Rationale
P0 P0-01 Resolve watched-file behavior mismatch: either implement real polling/watching or reframe as snapshot-time file inclusion. Person B usability; Person A reliable automation; end-user trust Docs imply watched-path polling, but code only resolves watched files during snapshot/sync.
P0 P0-02 Fix trigger snapshot failure visibility. Person B verification; end-user trust; Person A robustness Trigger snapshot failures may not be clearly surfaced to the user.
P0 P0-03 Make snapshot status accurate and user-visible. Person B clarity; LabArchives recordkeeping; end-user trust UI may say "queued," but execution happens inline and final status is not queryable.
P0 P0-04 Define and test run-all behavior. Person B low clutter; Person A robust trigger mechanics Run-all may create multiple rapid snapshot requests or inconsistent save behavior.
P0 P0-05 Rework trigger deduplication logic. Person A reliability; Person B verification Current fingerprinting can dedupe distinct executions in the same execution-count bucket.
P0 P0-06 Verify snapshot config precedence during actual snapshot execution. Person A configurability; Person B predictability UI/state config may not exactly match config used by snapshot execution.
P0 P0-07 Add full LabArchives logout/sign-out. Institutional safety; end-user account control There is in-memory session clearing, but no full route/UI/keyring cleanup.
P0 P0-08 Handle LabArchives session expiry distinctly. Person A robustness; institutional fit Expired sessions may appear authenticated until a generic LabArchives write failure occurs.
P0 P0-09 Prevent duplicate LabArchives page-name collisions. Person A reliable saving; Person B low friction Page names use second-level timestamps, so rapid saves can collide.
P0 P0-10 Handle partial LabArchives write failures. LabArchives recordkeeping; Person A traceability If page creation succeeds but later entries/attachments fail, cleanup or durable reporting is missing.
P0 P0-11 Add sensitive-file protections for watched files. Institutional safety; end-user trust No explicit denylist/warning for .env, credentials, hidden files, virtualenvs, caches, or large data folders.
P0 P0-12 Add symlink containment checks for watched paths. Institutional safety; maintainability Resolved paths may escape intended repo/notebook boundaries through symlinks.
P0 P0-13 Warn clearly that full notebooks with outputs are uploaded. End-user informed consent; institutional safety Full .ipynb files are uploaded with outputs, stdout/stderr, and embedded data intact.
P0 P0-14 Sanitize LabArchives path-template output. Institutional safety; maintainability Rendered template segments can include unsafe path elements such as "..".
P0 P0-15 Reconsider email-based default LabArchives paths. Privacy; institutional fit Generated config defaults to paths containing user email.
DONE P1-01 Separate rich notebook diff behavior from raw patch behavior. Raw patch attachments are filtered separately from rich notebook diffs.
DONE P1-02 Normalize or filter raw notebook patches. Notebook JSON and image patches are omitted from raw diff attachments when rich diffs cover them.
DONE P1-03 Improve output summaries for multi-output, image-only, and error-only cells. Summaries now cover all visible outputs and include image/error cases.
DONE P1-04 Stabilize figure filenames across cell reordering. Figure names now use notebook cell IDs plus output index, with index fallback only when IDs are unavailable.
DONE P1-05 Harden output-to-cell association. Output summaries and figure names carry cell IDs/output indexes, with tests for multi-output and image/error cases.
DONE P1-06 Distinguish new commit created from existing HEAD reused. Snapshot records and LabArchives metadata now expose commit_created/commit status.
DONE P1-07 Record git-success / LabArchives-failure cases. LabArchives write errors now include snapshot ID, commit hash/URL, and commit-created status in error context/logs.
DONE P1-08 Clarify dirty diff scope. LabArchives diff metadata and docs now state notebook/watched-path scope and raw-patch filtering.
DONE P1-09 Add backend-side validation for commit decisions. Snapshot execution rejects unresolved prompt commit mode.
DONE P1-10 Clarify tags versus true LabArchives tags. Metadata labels and docs now say tags are metadata text, not native LabArchives tags.
DONE P1-11 Add opt-in metadata extraction such as tagme. Backend parses tagme from extra_fields/default metadata and merges it into tags.
DONE P1-12 Expose or remove experiment context from the frontend. Frontend continues to normalize it away; docs call the old setting legacy/ignored.
DONE P1-13 Add upload size and save-frequency guardrails. Notebook/file upload limits, diff truncation, and per-notebook queue limits are in place.
DONE P1-14 Add progress reporting for long saves. Manual saves show an in-progress status and trigger saves emit JupyterLab notifications.
DONE P1-15 Show useful post-save references. Accepted snapshot responses and UI status now include snapshot ID, commit hash/URL, and LabArchives page details.
DONE P1-16 Make trigger snapshot activity visible when the sidebar is closed. Trigger snapshots now emit start/success/error JupyterLab notifications.
P2 P2-01 Consider AI-assisted post-processing for tags and summaries. Person B low manual burden; Person A future automation Useful later, but dependent on NIH/API constraints.
P2 P2-02 Add kernel-specific enrichment. Person A richer reproducibility README notes this is not implemented; defer until core behavior is stable.
P2 P2-03 Improve UI exposure of existing commit URL support. Person A traceability Commit URL generation exists, but post-save UI exposure is limited.
P2 P2-04 Explore structured LabArchives metadata fields. Person B searchability Current implementation uses rich-text metadata; structured fields depend on LabArchives API support.
P2 P2-05 Deduplicate identical image artifacts. Person B low clutter Repeated identical images can create unnecessary LabArchives clutter.
P2 P2-06 Add offline/degraded mode or durable retry queue. Person A robustness; end-user reliability Valuable, but larger architectural scope after failure visibility is fixed.
