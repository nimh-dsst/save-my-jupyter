# Core Targets

## The goal

> **Save Jupyter notebooks to LabArchives.**

Unpacked: when a notebook author working in JupyterLab decides "I want this state captured" — for posterity, sharing, compliance, or reproducibility — the system gets the notebook (and the context around it) into LabArchives. Reliably, without surprises, with enough trace to be useful weeks or months later.

Everything in the codebase is in service of that one sentence, or it shouldn't be there.

---

## The six targets

The system needs to do six things. Together they cover every user-facing contract. Dropping any one breaks the goal; over-investing in any one without the others gives no value.

```
                ┌───────────────────────────────────────────────┐
                │             T5 — CONFIGURE                    │
                │   (shapes what enters every stage below)      │
                └──────────────┬────────────────────────────────┘
                               │
   T2 ─────────  T1 ─────────  T3 ──────────  T4
TRIGGER  →    CAPTURE   →   DELIVER   →   CONFIRM
                               │
                ┌──────────────┴────────────────────────────────┐
                │             T6 — PROTECT                      │
                │   (validates what exits every stage above)    │
                └───────────────────────────────────────────────┘
```

TRIGGER → CAPTURE → DELIVER → CONFIRM is the pipeline. CONFIGURE shapes the pipeline's inputs; PROTECT validates the pipeline's outputs.

---

### T1 — CAPTURE

**Translate the notebook's current state into a structured bundle.**

A snapshot is a bundle of *what was true at this moment*. The system has to decide what goes in.

In the bundle today:
- the notebook file itself (with all outputs — explicitly disclosed to the user)
- inline figures pulled out of cell outputs (PNG/JPEG/SVG)
- working-tree files the user has flagged ("watched paths") that match at snapshot time
- git context — repo root, commit hash, remote URL, dirty state, scoped working-tree diff
- user-entered metadata — tags, notes, run label, free-form extras
- a short text summary of the last meaningful execution output

Deliberately not in the bundle:
- live kernel state (variables, package versions) — this is the kernel-independence boundary
- the entire working tree — only files the user has opted in
- raw `.ipynb` JSON noise — the rich notebook diff filters it out

**Why core:** without capture, there's nothing to deliver. The *shape* of capture is what determines whether a snapshot is useful later: enough context to reproduce, not so much that the snapshot is noise.

**Contracts under this target:** the CONTENT family, the GIT family, part of the WATCH family (the "what gets included" half).

---

### T2 — TRIGGER

**Decide when a capture fires.**

Two modes today:
- **Explicit**: the user clicks (panel, notebook toolbar, command palette). Always uncontested — manual snapshots never dedupe.
- **Automatic**: cell execution. Either a marked trigger cell or "every cell" mode. Successful executions only.

Plus a refinement:
- **Coalesce**: rapid bursts (e.g., Run All) collapse into one snapshot covering all triggered cells, not N snapshots.

What it isn't:
- Filesystem watching. The "watched paths" name is misleading — they're not polled; they're matched at trigger time. This is now explicit in the docs.
- Time-based scheduling. No cron, no "snapshot every N minutes."
- Save-on-save. The notebook getting saved doesn't fire a snapshot on its own.

**Why core:** the cadence of capture is itself a product decision. "Every cell" produces a fine-grained history; "marked cells" produces curated checkpoints; manual produces one-off records. A rewrite that fixes the cadence breaks the model.

**Contracts:** SNAP-MAN, SNAP-TRIG, the coalesce window, the trigger fingerprint composition.

---

### T3 — DELIVER

**Get the bundle into LabArchives.**

Three sub-concerns, in order:

1. **Authenticate.** One-time browser-redirect sign-in; persisted via OS keyring; restored across Jupyter restarts; session expiry surfaced distinctly from sign-out.
2. **Locate the destination.** Render a path template into a sequence of LabArchives directories, ending at a leaf where a new snapshot directory gets created. The template is configurable per-request, per-notebook, per-user, or per-repo.
3. **Write the directory.** One snapshot = one directory containing a canonical `00 Metadata` page plus one page per notebook attachment and one per watched file. Best-effort cleanup if the write fails partway.

Failure shapes the user trusts:
- Session expired → distinct code, auto-clears the session
- Page name would collide → fail, never overwrite
- Partial write → clean up before reporting
- LabArchives unreachable → fail immediately (no offline mode)

**Why core:** this is the unique value vs. "just save a notebook somewhere." Reliability matters more than performance — this is institutional recordkeeping. A flaky deliver makes the whole product untrustworthy.

**Contracts:** AUTH, DEST, TEMPLATE, the LabArchives half of FAIL, QUEUE.

---

### T4 — CONFIRM

**Tell the user what happened in terms they can act on.**

After every snapshot — successful or not — the user needs:
- Confirmation that the work is done (not "queued", not "in flight" — actually persisted before the message appears).
- A pointer to the result they can navigate to: job id, snapshot id, commit hash (with "created" vs "reused HEAD"), commit URL when buildable, LabArchives directory + page references.
- A clear failure explanation when it didn't work — coded by cause (session expired, file too large, queue full, etc.) — not "something went wrong."
- Ambient awareness for automatic snapshots, since the user wasn't watching: JupyterLab notifications for start (3s), success (5s), and failure (7s), all timed differently so the user can read them.

**Why core:** a save the user can't find isn't a save. Silent failures destroy trust faster than loud ones do. CONFIRM is the user's only proof the system works.

**Contracts:** the success/failure message shapes (SNAP-MAN-05, SNAP-TRIG-6/7/8), the FAIL vocabulary, the four status kinds, the post-save reference list.

---

### T5 — CONFIGURE (cross-cutting)

**Let individuals and teams shape capture, trigger, and delivery to match how they work.**

Four layers, highest precedence first:
1. Per-request (this snapshot's commit-mode choice)
2. Per-notebook (`metadata.save_my_jupyter` in the `.ipynb` — travels with the file)
3. Per-user (JupyterLab settings registry — defaults that follow the user)
4. Per-repo (`.save-my-jupyter.toml` — team defaults that travel in git)

Configurable surface:
- What gets captured: `include_notebook_file`, `include_diff_when_dirty`, the watched-paths list
- Where it lands: target LabArchives notebook + a path template with 16 substitutable variables
- How git participates: three commit modes, staging rules, commit message template
- Trigger policy: marked cells vs. every cell, per-notebook
- Tag/metadata defaults

Plus a one-click starter generator so users don't have to write the repo config from scratch.

**Why core:** capture/deliver have many "correct" answers depending on the project. Repo-level defaults let one team share a policy without each member configuring it. Notebook-level overrides let one experiment break that policy without changing the whole team's setup. Per-user defaults let an individual pick their own preferred commit mode without overriding the team. Without layering, you'd be choosing between "everyone same" and "nobody shares."

**Contracts:** the CONFIG family, the TEMPLATE variable catalog, the user-preference keys.

---

### T6 — PROTECT (cross-cutting)

**Don't leak credentials. Don't lose data. Don't surprise the user.**

What protection prevents, and where it intervenes in the pipeline:

| Risk | Stage | How it's prevented |
|---|---|---|
| Credentials in working tree → uploaded with snapshot | CAPTURE | Sensitive-filename denylist + parent-dir denylist (`.env`, `.pem`, `id_rsa*`, `.ssh/`, `.aws/`, …) |
| Symlinks escape the project root → arbitrary files uploaded | CAPTURE | Resolve, then re-check that the resolved path is inside the configured root |
| User pastes a path template with `..` → snapshot lands somewhere unexpected | DELIVER | Sanitize each path-template segment: reject `..`, drive letters, colons, control chars |
| Two snapshots in the same instant → overwrite | DELIVER | Page name = `<iso-ms>_<short-snapshot-id>`; guaranteed unique |
| Page creation succeeded, body upload failed → orphan directory in LabArchives | DELIVER | Best-effort move-to-API-Deleted-Items |
| User doesn't realize outputs are uploaded | CAPTURE / CONFIRM | Persistent disclosure banner in panel + docs |
| Notebook is huge → snapshot times out mid-upload | CAPTURE | Hard 50 MiB notebook cap and 25 MiB per-watched-file cap, rejected before any LabArchives call |
| Path-template default leaks user email into the LabArchives folder structure | CONFIGURE | Default starter config uses `{name}` (project), not `{user_email}` |
| User signed out but credentials still in keyring | AUTH | Sign-out deletes the keyring entry |

**Why core:** LabArchives is institutional recordkeeping. The system writes to a system that won't be casually corrected. Mistakes have consequences — both privacy (uploaded `.env`) and integrity (overwritten page, lost data). The user can't audit every snapshot. The system has to be safe by default.

**Contracts:** WATCH-10/11/12/13, AUTH-08/10, TEMPLATE-19/20/21/22/23, DEST-09/10, CONTENT-02/03, CONFIG-16/18.

---

## What is NOT a core target

These exist in the code but are *modes of access* or *quality concerns*, not goals in their own right:

- **Installation** — a prerequisite, not an ongoing value the user gets.
- **The HTTP API surface** — internal to the extension; the frontend and backend are designed together. A rewrite can change every endpoint as long as the frontend stays in sync.
- **The side panel's visual layout** — a concrete implementation of CONFIRM and CONFIGURE. The user wants to see what's resolved and tweak the inputs; the specific arrangement of sections is taste, not contract.
- **Toolbar / command palette / context menu** — implementations of TRIGGER (and CONFIGURE for the toggle-trigger commands). The current set is "what we shipped"; a rewrite could move them.
- **The settings registry / notebook-metadata schemas** — implementation of CONFIGURE.
- **Logging, error envelopes, run fingerprints** — operational machinery in service of CONFIRM and DELIVER.

None of these should *drive* the rearchitecture. The six targets should drive it; these should bend to fit.

---

## Pipeline orientation: a useful redrawing

The current code is organized by *layer* (handlers, services, adapters, domain). A rewrite organized around the six targets would look more like:

```
                    ┌──────────────────────────────┐
                    │      Configuration store     │  T5
                    │  (request → notebook → user  │
                    │       → repo → defaults)     │
                    └────────────┬─────────────────┘
                                 │ resolved policy
       ┌──────────┐    ┌─────────▼─────────┐    ┌──────────┐    ┌──────────┐
T2 →   │ Trigger  │ →  │   Capture engine  │ → │ Delivery │ → │ Confirm  │   → T4
       │ source   │    │  (bundle builder) │   │ adapter  │    │ surface  │
       └──────────┘    └────────┬──────────┘    └────┬─────┘    └──────────┘
                                │                    │
                                └──────────┬─────────┘
                                           ▼
                                    ┌──────────────┐
                                    │   Guards     │  T6
                                    │ (denylists,  │
                                    │  size caps,  │
                                    │  sanitizers, │
                                    │  cleanup)    │
                                    └──────────────┘
```

Each box is a swappable subsystem with a clear contract surface (the user contracts in `contracts.md`).

Notable consequences of this orientation:
- **Trigger sources are pluggable.** Manual / cell-execution / "Run All coalesce" are different *implementations* of a Trigger Source interface, not different code paths in one observer.
- **Capture engine is policy-driven.** Given a resolved policy and a notebook, it produces a bundle. No knowledge of LabArchives.
- **Delivery adapter is replaceable.** The LabArchives-specific bits (directory naming, page splitting, auth, cleanup) live behind one interface. Could be swapped for e.g. an S3 or "save to disk" adapter for testing.
- **Guards run at well-defined choke points** (input to capture, output of capture, output of template-render, output of delivery). Today they're scattered.
- **Confirm surface is one read-model** of "what just happened" — fed by both Delivery (success path) and Guards (failure path). Today they're scattered across panel status + Notification API.

---

## Implications for the rewrite

If we accept these six as the core targets, the rewrite questions become:

1. **What's the minimal contract surface for each target?** The user contracts I extracted are mostly observed-behavior; many can be simplified or retired during a rewrite (e.g., the four exact `(none)` / `(unavailable)` / `(no repository detected)` placeholders could collapse to one).
2. **Which targets are currently under-served and need investment?** My read: TRIGGER (the watched-paths gap was a symptom), CONFIRM (notifications are good but post-save linkability is weak — we surface page *names* but no URL).
3. **Which targets are currently over-served and could shrink?** CONFIGURE has 4 layers, 16 template variables, 7+ commit/staging knobs. Most users probably touch 2 of those. A rewrite could ship with the same surface but document a "minimal config story" path.
4. **Where does PROTECT need teeth?** Today it's mostly automatic guards. Notebook output redaction (a user-asked-for feature) is OS-04. A first-class redactor would belong in the guards box.

I'd push back on:
- Adding more triggers (real polling, time-based) before T2's existing trigger story is rock-solid.
- Adding more capture surface (kernel variables, environment fingerprints) before T1's existing capture is observable and predictable.
- More configuration layers — four is already at the edge of intelligible.
