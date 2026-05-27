# Development

## Requirements

- Python `3.12+`
- Node.js and npm
- JupyterLab `4.x` available in the Python environment if you want editable
  frontend install behavior

## Initial Setup

```bash
npm ci
uv sync --group dev
```

If editable install wiring fails because `jupyterlab.labextensions` is missing,
install JupyterLab into that environment first and rerun the command.

## Common Commands

### Frontend

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

Notes:

- `npm run build` compiles the TypeScript frontend and produces the bundled
  labextension assets in `save_my_jupyter/labextension`
- the production build uses a local `jupyterlab_core` manifest so it can bundle
  the extension without depending on a full Python-side JupyterLab install

### Backend

```bash
python -m ruff check save_my_jupyter tests
uv run ty check save_my_jupyter tests
uv run pytest tests -p no:cacheprovider
```

### Pre-commit

```bash
pre-commit install
pre-commit run --all-files
```

## Editable Installs

The Python package uses `hatch-jupyter-builder`.

Editable installs call:

```bash
npm run install:extension
```

That script currently runs:

```bash
python -m jupyterlab.labextensions develop . --overwrite
```

Use a Python environment that already has JupyterLab installed when relying on
editable frontend wiring.

## Development Workflow

The intended workflow is:

1. keep `npm ci` and `uv sync --group dev` current
2. make a small backend or frontend change
3. add or update the corresponding unit tests immediately
4. run the affected lint, typecheck, and test commands before moving on
5. run the full local verification set before packaging or opening a PR

The project is intentionally strict about unit tests and static analysis as code
is added.

## Test-Driven Workflow

`AGENTS.md` (and its `CLAUDE.md` symlink) is the authoritative workflow guide.
Every behavior change follows red → green → refactor:

1. Find or write the user-observable behavior in `contracts.md`. That file is the
   spec; `targets.md` explains how the spec is organized around the six targets.
2. Write the smallest failing test against the public surface and confirm it fails
   for the right reason.
3. Make it green with the smallest change.
4. Re-run the local gate; refactor; re-run.

Pure mechanical changes (renames, formatting, dependency bumps) are exempt.

### Contract-ID test convention

Tests cite the contract they verify by stable ID, so a reader can map a test back
to the promise it protects. Put the ID in the test name or a leading comment:

```python
def test_errored_run_still_snapshots_with_run_outcome_error() -> None:
    # C-SNAP-07: an errored trigger run is captured with run_outcome = error
    ...
```

A contract without a test is a defect to fix the next time the area is touched.

## Architecture & Import Rules

The package uses a layered hexagonal structure. Allowed import direction:

```text
http/    -> application/ -> ports/ -> adapters/
worker/  -> application/ -> ports/ -> adapters/
application/ -> domain/
adapters/    -> domain/
```

Hard rules, enforced by lint and by `tests/test_architecture.py` (an AST test):

- `domain/` imports nothing from the project except itself.
- `ports/` imports only `domain/` (Protocol seams over `domain` types).
- `application/` and `domain/` must not import Tornado, dulwich, labapi, sqlite3,
  keyring, or requests. IO happens only through `ports/` Protocols, implemented in
  `adapters/`.
- `application/` is not all pure: config resolution, capture planning, bundle
  building, and message formatting are pure; orchestrators perform IO only through
  ports. `git/inspect.py` and capture file reads are read-only adapters
  (side-effect-free but not pure); `git/mutate.py` and deliveries are side effects.

If the architecture test fails, a forbidden import has crossed a layer boundary —
move the IO behind a port rather than relaxing the test.

## Packaging

Build artifacts:

```bash
uv build --wheel --sdist
```

Expected outputs:

- `dist/save_my_jupyter-<version>-py3-none-any.whl`
- `dist/save_my_jupyter-<version>.tar.gz`

The wheel should include:

- bundled frontend assets under
  `share/jupyter/labextensions/@save-my-jupyter/extension`
- server extension registration under
  `etc/jupyter/jupyter_server_config.d/save_my_jupyter.json`

## Test Strategy

The repository uses:

- strict backend parsing tests
- backend service and runtime tests
- frontend unit tests compiled with `tsconfig.test.json`
- strict lint and type gates for both Python and TypeScript

Current local verification set:

```bash
python -m ruff check save_my_jupyter tests
uv run ty check save_my_jupyter tests
uv run pytest tests -p no:cacheprovider
npm run lint
npm run typecheck
npm test
npm run build
```

For release-style packaging verification:

```bash
uv build --wheel --sdist
```

## CI

CI is defined in:

- `.github/workflows/ci.yml`

It covers:

- Python lint, typecheck, and tests
- frontend lint, typecheck, tests, and build
- wheel and sdist creation

## LabArchives Development Dependency

`labapi` is a required dependency declared in project metadata, so the active
Python environment should get it automatically when you install or sync the
project.

If you are working on `labarchives-api` in parallel, install it into that same
environment, for example with an editable install, instead of relying on a
checked-out source tree being discovered automatically.

## Project Layout

- `save_my_jupyter/`
  Python backend package
- `src/`
  JupyterLab frontend source
- `style/`
  frontend styles
- `tests/`
  backend unit and runtime tests
- `ui_tests/`
  frontend unit tests
- `plan.md`
  architecture plan
- `checklist.md`
  implementation checklist
