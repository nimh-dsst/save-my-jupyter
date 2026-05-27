# AGENTS.md

Guidance for agentic coding tools (Codex, Claude Code, others) working in this repository.

The workflow here is **test-driven**. Tests are the spec. The rest of this file explains how to apply that here.

## Core loop: red → green → refactor

For every behavior change, follow this loop. Do not skip steps even when "I know what to write."

1. **Identify the contract.** Find or write the user-observable behavior that should hold. `contracts.md` is the canonical spec. If the behavior isn't in `contracts.md`, decide whether it belongs there before you add code.
2. **Write the smallest failing test.** Express the contract as a test against the public surface — a backend service, an HTTP handler, a frontend module's exports. Aim for one assertion per concept; multiple tests are fine.
3. **Run the test. Confirm it fails for the right reason.** "Right reason" means the symptom you'd predict from the contract being unimplemented — `AttributeError`, an assertion on a missing field, a status code that's wrong. If it fails for some other reason (import error, fixture broken, typo), fix the test first.
4. **Make it green with the smallest code change.** Implement just enough to pass. Do not generalize speculatively. Do not refactor unrelated code in the same step.
5. **Re-run the local gate** (see Verification below). Anything that wasn't part of this change should still be green.
6. **Refactor.** Tidy the implementation, lift duplication, rename for clarity. Re-run the gate after.

Exceptions where TDD does not apply: pure mechanical fixes (renames, reformatting, comment-only edits), dependency bumps, and config-file tweaks that don't change behavior. Use judgment; when in doubt, write the test.

## Anti-patterns

- **Implementing before testing.** "I'll add the test after" almost always means the test ends up shaped around the code rather than the contract.
- **Tests that mirror implementation.** Mock-heavy tests that pin internal calls will break on every refactor and don't protect any contract. Test against public observable behavior.
- **Adding a contract because the test asks for it.** If a test is awkward to write, that usually means the contract is unclear — fix `contracts.md` first.
- **Treating CI green as proof.** Run the local gate before you commit; CI is the backstop.
- **Marking work complete because a related test passes.** A contract is complete only when its own test exists and is green.

## Verification gate

After every green step, before any commit, before any PR:

```powershell
uv run ruff format --check .
uv run ruff check save_my_jupyter tests scripts/selenium_smoke.py
uv run ty check save_my_jupyter tests
uv run pytest
npm run lint
npm run typecheck
npm test
npm run build:lib
```

This matches CI exactly (`.github/workflows/ci.yml`). When iterating, the focused commands are faster:

Single backend test:

```powershell
uv run pytest tests/test_snapshot_service.py::test_name -p no:cacheprovider
```

Single frontend test (tests are compiled to `test-dist/` first):

```powershell
npm run test:build
node --test --test-isolation=none test-dist/ui_tests/name.test.js
```

The repo accumulates throwaway scratch directories during test runs: `tmp-runtime-*`, `tmp-snapshot-service-*`, `selenium-profile-*`, `jupyter-workspaces-*`, `pytest-cache-files-*`. Treat them as test output, do not add them to git, and clean them up after use so the directory listing stays readable.

## Where tests live

The mapping from source modules to their tests:

**Backend** (`save_my_jupyter/` → `tests/`):

- `handlers.py` → `tests/test_handlers_behavior.py`
- `config/` → `tests/test_config.py`, `tests/test_notebook_metadata.py`
- `git/service.py` → `tests/test_runtime_services.py`
- `services/artifacts.py`, `services/coordinator.py`, `services/run_fingerprint.py` → `tests/test_services.py`
- `services/auth.py`, `adapters/labarchives.py` → `tests/test_runtime_services.py`
- `services/snapshot.py` → `tests/test_snapshot_service.py`
- `api/parsers.py` → `tests/test_api_parsers.py`
- `api/responses.py` → `tests/test_api_responses.py`
- `parsing.py`, `watch_paths.py` → `tests/test_parsing.py`, `tests/test_watch_paths.py`

**Frontend** (`src/` → `ui_tests/`):

- `apiClient.ts`, `types.ts` → `ui_tests/types.test.ts`
- `metadata.ts` → `ui_tests/metadata.test.ts`
- `notebook/triggerHooks.ts` → `ui_tests/triggerHooks.test.ts`
- `notebook/requestBuilders.ts` → `ui_tests/requestBuilders.test.ts`
- `notebook/pathValidation.ts` → `ui_tests/pathValidation.test.ts`
- `panelFormatting.ts` → `ui_tests/panelFormatting.test.ts`
- `panelState.ts`, `panelBehavior.ts` → `ui_tests/panelState.test.ts`, `ui_tests/plugin.test.ts`
- `settings.ts` → `ui_tests/settings.test.ts`
- `signals.ts` → `ui_tests/signals.test.ts`
- `tags.ts` → `ui_tests/tags.test.ts`
- `authEvents.ts` → `ui_tests/authEvents.test.ts`

If a module has no test file, that is itself a defect to fix the next time you touch the module.

## Test style

- Test names describe behavior, not the code path: `test_snapshot_request_loads_notebook_metadata_for_planning`, not `test_plan_snapshot_calls_load_notebook_metadata`.
- Backend fakes (`FakeSnapshotService`, `FakeLabApiModule`, `FakeKeyringBackend`) live alongside real tests in the same file. Reuse them; do not invent parallel fakes.
- Frontend tests compile through `tsconfig.test.json` to `test-dist/` and run under `node --test`. There is no React renderer in tests; verify behavior through the modules' exports, not by mounting components.
- Each test sets up its own state and cleans up its own temp dirs (`Path.cwd() / ".test_*"`). Tests must not depend on order.
- Skip rather than fail when a precondition genuinely can't be met (e.g., symlink tests on Windows): use `pytest.mark.skipif` with a reason string.

## Project shape

`save-my-jupyter` ships one Python-distributed Jupyter extension with two runtime parts:

- `save_my_jupyter/`: Jupyter Server extension, Python 3.12+, backend orchestration, config resolution, Git integration, artifact collection, LabArchives auth, and LabArchives persistence.
- `src/`: JupyterLab 4 / Notebook 7 frontend extension, TypeScript + React, right-side panel, commands, toolbar integration, notebook/cell metadata, trigger-cell execution capture, and backend API calls.

Built frontend assets are generated into `save_my_jupyter/labextension/` and bundled into the wheel by `hatch-jupyter-builder`.

## Backend architecture

Entry point `save_my_jupyter/extension.py:SaveMyJupyterApp` wires a `ServiceContainer` into Jupyter settings and registers Tornado handlers under `/save-my-jupyter/*`.

- `handlers.py` is the HTTP boundary: parse JSON with `api/parsers.py`, call services, serialize with `api/responses.py`. Keep handlers thin; behavior lives in services.
- `config/` resolves `.save-my-jupyter.toml`, notebook metadata, user settings, and effective config (four-layer merge — see `contracts.md` C-CONFIG-01).
- `git/service.py` is dulwich-based: repo discovery, dirty state, diff generation, staging, commit creation, commit URL generation.
- `services/artifacts.py` is kernel-independent notebook / figure / diff / watched-file artifact collection.
- `services/auth.py` handles LabArchives interactive auth and stored-profile lifecycle.
- `adapters/labarchives.py` is the only layer that talks to `labapi`; it maps one snapshot to one LabArchives directory.
- `services/snapshot.py`, `services/coordinator.py`, `services/run_fingerprint.py` handle planning, execution, queueing, and automatic trigger dedupe.

Core models live in `domain/` and stay narrow and typed: `NewType` identifiers, `StrEnum` wire values, frozen slotted dataclasses, and explicit result unions.

## Frontend architecture

The JupyterLab plugin is `src/plugin.ts` with id `@save-my-jupyter/extension:plugin`. The pieces:

- `ApiClient` — backend calls and runtime response parsing.
- `NotebookMetadataStore` — notebook and cell metadata reads/writes.
- `UserPreferencesStore` — settings-registry-backed preferences.
- `SnapshotPanel` — React right-sidebar UI.
- `SnapshotPanelController` — UI behavior, state transitions, API calls.
- `ExecutionObserver` — listens to `NotebookActions.executed` and submits trigger-cell snapshots (with per-notebook coalescing).
- `signals.ts` — simple state signal used to render the panel.

All JSON boundaries parse through zod schemas in `src/types.ts`. Adding a backend field requires updating the schema and a test against the parser.

## Hard requirements

- Preserve kernel independence. Core behavior must not require installing the package in the notebook kernel, importing helper code from notebooks, or kernel monkey-patching.
- Parse HTTP, TOML, notebook metadata, Git, and LabArchives data at the boundary before service logic sees it.
- Avoid raw dicts and `Any` in core service interfaces.
- Snapshot commits must not stage unrelated repository files.
- Watched paths must remain relative and contained in the allowed root.
- LabArchives persistence stays isolated behind `adapters/labarchives.py`.

## Code style

- Python files start with `from __future__ import annotations`.
- Ruff is formatter and linter; configuration in `pyproject.toml`. Do not add local `# noqa` without checking the global config.
- Type checking is Astral `ty`, not mypy or pyright.
- TypeScript: strict `tsc`, ESLint, zod schemas, separate compiled UI tests under `test-dist/`.
- Make small focused commits per red→green→refactor cycle; do not bundle unrelated changes.

## Where to find what

- `contracts.md` — the canonical user-observable behavior the tests verify against.
- `targets.md` — architectural targets the system is organized around.
- `TODO.md` — active product/quality backlog (do not assume items are done just because `checklist.md` marks them complete).
- `plan.md` — broader architecture and compatibility policy.
- `checklist.md` — historical context; may overstate completion.
- `docs/` — user-facing usage, configuration, development, troubleshooting.

When implementation and `docs/` disagree, fix the disagreement (with a test) or explicitly mark the feature as deferred. When implementation and `contracts.md` disagree, prefer fixing the implementation — that file is the spec.
