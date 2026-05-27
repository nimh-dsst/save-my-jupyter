"""Pure working-tree diff filtering (target CAPTURE/CONTENT, contracts
C-CONTENT-05/06). The git adapter produces a raw patch; this drops the notebook
JSON section (the rich notebook diff represents it) and image-file sections, and
truncates to ~1 MB. No IO."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

DIFF_FILTER_QUALIFIER = (
    "Filtered working tree patch; notebook JSON and image patches are omitted"
)

_MAX_LENGTH = 1_000_000
_SECTION_PATH_PATTERN = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_IMAGE_SUFFIXES = frozenset(
    {".png", ".jpeg", ".jpg", ".gif", ".svg", ".bmp", ".tif", ".tiff", ".webp", ".avif"}
)


def filter_diff(diff_text: str, *, notebook_relative_path: str | None) -> str | None:
    sections = _split_sections(diff_text)
    if not sections:
        return _truncate(diff_text) if diff_text.strip() else None

    kept: list[str] = []
    for section in sections:
        path = _section_path(section)
        if path is None:
            kept.append(section)
            continue
        if path == notebook_relative_path and path.endswith(".ipynb"):
            continue
        if _is_image(path):
            continue
        kept.append(section)

    if not kept:
        return None
    return _truncate("\n\n".join(kept))


def _split_sections(diff_text: str) -> tuple[str, ...]:
    sections: list[list[str]] = []
    current: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if current:
                sections.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        sections.append(current)
    return tuple("\n".join(lines).strip() for lines in sections)


def _section_path(section: str) -> str | None:
    first_line = section.splitlines()[0] if section else ""
    match = _SECTION_PATH_PATTERN.match(first_line)
    return match.group(2) if match is not None else None


def _is_image(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in _IMAGE_SUFFIXES


def _truncate(diff_text: str) -> str:
    if len(diff_text) <= _MAX_LENGTH:
        return diff_text
    omitted = len(diff_text) - _MAX_LENGTH
    suffix = f"\n\n[Diff truncated; omitted {omitted} characters.]"
    return diff_text[: _MAX_LENGTH - len(suffix)] + suffix
