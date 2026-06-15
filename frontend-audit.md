# Frontend contract audit — rebuilt UI vs. `contracts.md`

Status: ✅ present · ⚠️ partial · ❌ missing. "Backend" notes whether the
server already supports it (so the work is UI-only).

The rebuilt panel currently renders only **Readiness → Snapshot button →
Activity**, in stripped form. Most user-facing contracts below are unmet.

## Panel structure (C-PANEL)

| Contract | What it requires | Status | Notes |
|---|---|---|---|
| C-PANEL-01 | Right sidebar, **not closable**, header "Save My Jupyter", openable via palette `Open Snapshot Settings` / toolbar / tab | ⚠️ | Right sidebar ✅, header ✅. **Bug:** panel is `closable=true` (should be false). No `Open Snapshot Settings` command. |
| C-PANEL-02 | `Snapshot now` **and** `Refresh` near top; primary disabled w/ reason when blocked | ⚠️ | Snapshot now ✅, disabled+blocked msg ✅. **No Refresh action.** |
| C-PANEL-03 | Five sections in order: Readiness, **What will be saved**, **Snapshot options**, **Setup**, Activity | ❌ | Only Readiness + bare Snapshot + Activity. Two whole sections missing. |
| C-PANEL-04 | Readiness shows notebook path, connection, **destination**, **git state**, blocking issues; "open a notebook" when none | ⚠️ | Auth desc ✅, notebook name ✅, blocked msg ✅. Missing destination, git/repo state, no-notebook message. |
| C-PANEL-05 | Persistent output-upload disclosure, `role="note"`, not dismissible | ❌ | Not rendered. |
| C-PANEL-06 | "What will be saved" from backend `/snapshot-preview` (no UI re-merge) | ❌ | `willBeSaved` view-model + backend preview exist but **never wired**; preview not fetched. |
| C-PANEL-07 | Snapshot options: commit mode, trigger mode, trigger-cell state, watched paths, **tags**, **run label**, **notes**; refresh review on change | ❌ | Entire section missing. Request builder accepts these; nothing collects them. |
| C-PANEL-08 | Setup: connect, sign out, starter-config create/check | ⚠️ | Connect/sign-out live (in Readiness). No config-init. Not a Setup section. |
| C-PANEL-09 | Activity: running job phases, last receipt persists, failures inspectable | ⚠️ | Basic rows ✅. No phase-level progress; no dismiss. |
| C-PANEL-10 | Status kinds info/success/warning/error + `aria-live="polite"`; explicit empty values | ⚠️ | Plain status string; no kinds, no aria-live. |

## Toolbar (C-TOOLBAR)

| Contract | Requires | Status |
|---|---|---|
| C-TOOLBAR-01 | Snapshot button in **every notebook toolbar** | ❌ missing |
| C-TOOLBAR-02 | Trigger cells get a brand-color left-edge accent decoration | ❌ missing |

## Commands & context menu (C-CMD)

| Contract | Requires | Status |
|---|---|---|
| C-CMD-01 | Palette: snapshot, open panel, toggle trigger, mark/unmark trigger, toggle all-cells | ⚠️ only `Snapshot Now`; the rest missing |
| C-CMD-02 | Right-click cell → trigger-toggle entry with adaptive label | ❌ missing |
| C-CMD-03 | All-cells confirm messages + "select a cell" warning | ❌ missing |

## Triggers (C-SNAP-07/08, C-CONFIG-05/06)

| Capability | Status | Notes |
|---|---|---|
| Mark/unmark a cell as a trigger (write `cell.metadata.save_my_jupyter.trigger`) | ❌ | **No UI at all.** Observer reads it, nothing sets it — triggers are unusable. |
| All-cells-trigger toggle | ❌ missing |
| Accumulate-and-flush coalescing (run → one snapshot) | ✅ | `triggerCoalescer` + `executionObserver` wired. |
| Fire trigger snapshot on run completion | ✅ wired (untested in browser) |

## Snapshot flow (C-SNAP)

| Contract | Requires | Status | Notes |
|---|---|---|---|
| C-SNAP-01 | Fire from panel + toolbar + palette | ⚠️ | Panel ✅, palette ✅, **toolbar ❌**. |
| C-SNAP-02 | Unauth → modal "LabArchives connection required" + readiness line | ⚠️ | Readiness line ✅; modal dialog ❌. |
| C-SNAP-03 | Save notebook (`panel.context.save()`) before snapshot | ❌ | Not called before submit. |
| C-SNAP-04 | Activity "Saving notebook, creating…/uploading" until done | ⚠️ | One static status; no phases. |
| C-SNAP-05 | Success status `Snapshot saved. …` + JupyterLab notification | ⚠️ | Backend `display_message` ✅; panel shows "Snapshot queued" then activity row; **no notification**. |
| C-SNAP-06/07 | Failure fallbacks; trigger emits 3 notifications | ⚠️/❌ | Backend messages ✅; **no notifications**. |

## Metadata inputs (C-CONTENT-08, C-DIRECTIVE-03)

| Capability | Status | Notes |
|---|---|---|
| Editable **tags** (manual, pre-filled from `smj:` directive) | ❌ | Backend merges directive+UI+config; UI input missing. |
| Editable **run label** | ❌ missing |
| **Notes** field | ❌ missing |
| `smj:` directive parsing (tags/run from code) | ✅ | `directives.ts` (+ shared fixtures). |

## Auth UI (C-AUTH)

| Contract | Status | Notes |
|---|---|---|
| C-AUTH-01 Connect → new tab → broadcast → panel updates | ⚠️ | Wired, but **login is currently failing** (open bug) — no session created. |
| C-AUTH-03 four status phrasings | ✅ | `readiness.ts`. |
| C-AUTH-04 button toggle + signing-out transitional messages | ⚠️ | Toggle ✅; transitional `Signing out…`/`Signed out` messages ❌. |
| C-AUTH-05 expired-session message | ❌ missing |
| C-AUTH-06 callback page + **60 s pending auto-cancel** + Refresh | ⚠️ | Page ✅; 60 s auto-cancel ❌; Refresh ❌. |
| C-AUTH-09 notebook target picker from `storedNotebookNames` | ❌ missing |

## Bottom line

Backend supports essentially all of this. The gap is frontend: **two missing
panel sections (What will be saved, Snapshot options), Setup, the entire
trigger-marking surface (toolbar button, cell decoration, commands, context
menu), tags/run-label/notes inputs, the output disclosure, Refresh,
notifications, save-before-snapshot, and the panel-closable bug** — plus the
open auth-login bug that blocks any real snapshot.
