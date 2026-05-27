"""Pure-function safety guards (target PROTECT). No IO: callers pass in sizes and
resolved paths; these functions only decide and, where a contract says so, raise
``SnapshotError`` with a stable code. Ported and consolidated from the legacy
``watch_paths.py`` and ``adapters/path_templates.py``."""

from __future__ import annotations

import re
import sys
from fnmatch import fnmatchcase
from pathlib import PurePath, PurePosixPath

from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.domain.guards import (
    WatchedPathAccepted,
    WatchedPathRejected,
    WatchedPathValidation,
)

# Upload size caps (contracts C-CONTENT-01, C-WATCH-08).
NOTEBOOK_MAX_BYTES = 50 * 1024 * 1024
WATCHED_FILE_MAX_BYTES = 25 * 1024 * 1024

# Credential / build / cache exclusions (contracts C-WATCH-06, C-WATCH-07).
SENSITIVE_FILENAME_PATTERNS: tuple[str, ...] = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_ed25519*",
    "id_ecdsa*",
    ".netrc",
    ".htpasswd",
    "*.p12",
    "*.pfx",
    "credentials",
    "credentials.json",
)
SENSITIVE_PARENT_DIR_PARTS = frozenset({".aws", ".ssh"})
IGNORED_PATH_PARTS = frozenset(
    {
        ".git",
        ".ipynb_checkpoints",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".uv-cache",
        ".venv",
        "__pycache__",
        "env",
        "node_modules",
        "venv",
    }
)

_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_DRIVE_LETTER = re.compile(r"^[A-Za-z]:$")
_CONTROL_CHARACTERS = frozenset(chr(code) for code in range(32)) | {"\x7f"}
_GLOB_CHARACTERS = frozenset("*?[")
_FILENAMES_ARE_CASE_INSENSITIVE = sys.platform == "win32"
_UNSAFE_SEGMENT_CODE = "unsafe_labarchives_target_path"


def validate_watched_path(raw: str) -> WatchedPathValidation:
    """Validate a user-entered watched path (contract C-WATCH-02). Returns the
    normalized POSIX path or a rejection carrying the exact user-facing message."""
    trimmed = raw.strip()
    if trimmed == "":
        return WatchedPathRejected(
            message="Watched paths must not be empty.",
            code="invalid_sequence_item",
        )
    if (
        trimmed.startswith(("/", "\\\\"))
        or _WINDOWS_ABSOLUTE.match(trimmed) is not None
    ):
        return WatchedPathRejected(
            message="Watched paths must be relative.",
            code="absolute_path_not_allowed",
        )

    segments: list[str] = []
    for segment in re.split(r"[\\/]+", trimmed):
        if segment in ("", "."):
            continue
        if segment == "..":
            return WatchedPathRejected(
                message="Watched paths must stay within the notebook or repo root.",
                code="path_escapes_root",
            )
        segments.append(segment)

    if not segments:
        return WatchedPathRejected(
            message="Watched paths must include at least one path segment.",
            code="invalid_sequence_item",
        )
    return WatchedPathAccepted(normalized="/".join(segments))


def is_glob(pattern: str) -> bool:
    return any(character in _GLOB_CHARACTERS for character in pattern)


def is_within_root(resolved: PurePath, root: PurePath) -> bool:
    """True if ``resolved`` is the root or contained in it (contract C-WATCH-05).
    Pure path logic; the caller resolves symlinks before calling."""
    try:
        return resolved == root or resolved.is_relative_to(root)
    except ValueError:
        return False


def is_ignored_path(path: PurePath) -> bool:
    """True if any path part is a build/cache/venv directory (contract C-WATCH-07)."""
    return any(part in IGNORED_PATH_PARTS for part in path.parts)


def is_sensitive_file(path: PurePath) -> bool:
    """True if the file sits under a credential dir or matches a credential
    filename pattern (contract C-WATCH-06)."""
    name = path.name
    if _FILENAMES_ARE_CASE_INSENSITIVE:
        if any(part.lower() in SENSITIVE_PARENT_DIR_PARTS for part in path.parts):
            return True
        lowered = name.lower()
        return any(
            fnmatchcase(lowered, pattern.lower())
            for pattern in SENSITIVE_FILENAME_PATTERNS
        )
    if any(part in SENSITIVE_PARENT_DIR_PARTS for part in path.parts):
        return True
    return any(fnmatchcase(name, pattern) for pattern in SENSITIVE_FILENAME_PATTERNS)


def matches_watch_pattern(*, candidate: str, pattern: str) -> bool:
    """Match a POSIX candidate path against a watched-path pattern. Non-glob
    patterns match the path or any path beneath it (contract C-WATCH-03)."""
    if is_glob(pattern):
        candidate_path = PurePosixPath(candidate)
        return any(candidate_path.match(variant) for variant in _glob_variants(pattern))
    return candidate == pattern or candidate.startswith(f"{pattern}/")


def enforce_size_cap(
    *, size_bytes: int, max_bytes: int, code: str, path: PurePath
) -> None:
    """Raise ``SnapshotError`` when a file exceeds its cap (contracts C-CONTENT-01,
    C-WATCH-08). Pure: the size is supplied by the read-only filesystem adapter."""
    if size_bytes > max_bytes:
        raise SnapshotError(
            f"{path.name} is {size_bytes} bytes, over the {max_bytes}-byte limit.",
            code=code,
            context={"path": str(path), "size": str(size_bytes)},
        )


def sanitize_path_segment(segment: str, *, template: str) -> str | None:
    """Sanitize one rendered LabArchives path segment (contract C-TEMPLATE-03).
    Returns the cleaned segment, ``None`` to drop it, or raises on an unsafe one."""
    trimmed = segment.strip()
    if trimmed == "..":
        raise SnapshotError(
            "LabArchives target path segment may not traverse parents.",
            code=_UNSAFE_SEGMENT_CODE,
            context={"template": template, "segment": segment},
        )
    stripped = trimmed.rstrip(".")
    if stripped in ("", "."):
        return None
    if _DRIVE_LETTER.match(stripped) is not None or ":" in stripped:
        raise SnapshotError(
            "LabArchives target path segment may not contain a drive letter or colon.",
            code=_UNSAFE_SEGMENT_CODE,
            context={"template": template, "segment": segment},
        )
    if any(character in _CONTROL_CHARACTERS for character in stripped):
        raise SnapshotError(
            "LabArchives target path segment may not contain control characters.",
            code=_UNSAFE_SEGMENT_CODE,
            context={"template": template, "segment": segment},
        )
    return stripped


def _glob_variants(pattern: str) -> tuple[str, ...]:
    variants = {pattern}
    pending = [pattern]
    while pending:
        current = pending.pop()
        marker = current.find("**/")
        if marker == -1:
            continue
        variant = current[:marker] + current[marker + 3 :]
        if variant not in variants:
            variants.add(variant)
            pending.append(variant)
    return tuple(variants)
