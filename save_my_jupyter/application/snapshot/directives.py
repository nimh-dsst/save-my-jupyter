"""Static parser for in-source `# smj:` directives (target CAPTURE, contracts
C-DIRECTIVE-01/02, C-CONTENT-08). Pure: it reads cell source strings and never
executes anything, so it needs no kernel package, import, or IPython hook. The
frontend mirror in ``src/application/directives.ts`` must match this behavior;
the shared fixtures in ``tests/test_directives.py`` guard that contract."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from save_my_jupyter.domain.capture import DirectiveResult

# Only full-line comments are directives. Trailing inline comments are ignored so
# that `#` inside a string literal on a code line cannot masquerade as a directive
# (we parse statically, without tokenizing the source).
_COMMENT_MARKERS = ("#", "//")
_PREFIX = "smj:"


def parse_directives(cell_sources: Sequence[str]) -> DirectiveResult:
    run_label: str | None = None
    tags: list[str] = []
    seen: set[str] = set()
    for source in cell_sources:
        for line in source.splitlines():
            body = _directive_body(line)
            if body is None:
                continue
            line_run, line_tags = _parse_body(body)
            if line_run is not None and run_label is None:
                run_label = line_run
            for tag in line_tags:
                if tag not in seen:
                    seen.add(tag)
                    tags.append(tag)
    return DirectiveResult(run_label=run_label, tags=tuple(tags))


def merge_tags(*sources: Iterable[str]) -> tuple[str, ...]:
    """Union tags across sources (directives, UI, config defaults), whitespace-
    trimmed and de-duplicated in first-seen order (contract C-CONTENT-08)."""
    merged: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for tag in source:
            trimmed = tag.strip()
            if trimmed and trimmed not in seen:
                seen.add(trimmed)
                merged.append(trimmed)
    return tuple(merged)


def _directive_body(line: str) -> str | None:
    stripped = line.lstrip()
    for marker in _COMMENT_MARKERS:
        if stripped.startswith(marker):
            comment = stripped[len(marker) :].lstrip()
            if comment[: len(_PREFIX)].lower() == _PREFIX:
                return comment[len(_PREFIX) :].strip()
            return None
    return None


def _parse_body(body: str) -> tuple[str | None, list[str]]:
    run: str | None = None
    tags: list[str] = []
    for pair in body.split(";"):
        if "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        normalized_key = key.strip().lower()
        trimmed_value = value.strip()
        if normalized_key == "run":
            if run is None and trimmed_value:
                run = trimmed_value
        elif normalized_key == "tags":
            tags.extend(tag.strip() for tag in trimmed_value.split(",") if tag.strip())
    return run, tags
