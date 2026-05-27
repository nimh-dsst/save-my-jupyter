from __future__ import annotations

import fnmatch
import logging
import sys
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from dulwich import porcelain
from dulwich.repo import Repo

from save_my_jupyter.domain.types import RelativeWatchPath
from save_my_jupyter.parsing import normalize_path

if TYPE_CHECKING:
    from dulwich.porcelain import GitStatus

_logger = logging.getLogger(__name__)
_GLOB_CHARACTERS = frozenset("*?[")
_IGNORED_PATH_PARTS = frozenset(
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
_SENSITIVE_FILENAME_PATTERNS: tuple[str, ...] = (
    ".env",
    ".env.*",
    ".htpasswd",
    ".netrc",
    "*.key",
    "*.p12",
    "*.pem",
    "*.pfx",
    "credentials",
    "credentials.json",
    "id_ecdsa*",
    "id_ed25519*",
    "id_rsa*",
)
_SENSITIVE_PARENT_DIR_PARTS = frozenset({".aws", ".ssh"})
_FILENAMES_ARE_CASE_INSENSITIVE = sys.platform == "win32"


def resolve_watch_files(
    *,
    capture_root: Path,
    repo_root: Path | None,
    watch_paths: Iterable[RelativeWatchPath],
) -> tuple[Path, ...]:
    normalized_watch_paths = tuple(str(path) for path in watch_paths)
    if not normalized_watch_paths:
        return ()

    if repo_root is None:
        return _resolve_files_from_filesystem(
            capture_root=capture_root,
            watch_paths=normalized_watch_paths,
        )

    resolved_repo_root = repo_root.resolve()
    watched_files: dict[str, Path] = {}
    for relative_path in resolve_watch_targets(
        repo_root=resolved_repo_root,
        watch_paths=watch_paths,
    ):
        absolute_path = (resolved_repo_root / relative_path).resolve()
        if not absolute_path.is_file():
            continue
        if not _passes_safety_gates(absolute_path, container=resolved_repo_root):
            continue
        watched_files[str(absolute_path)] = absolute_path

    return tuple(watched_files[key] for key in sorted(watched_files))


def resolve_watch_targets(
    *,
    repo_root: Path,
    watch_paths: Iterable[RelativeWatchPath],
) -> list[str]:
    normalized_watch_paths = tuple(str(path) for path in watch_paths)
    if not normalized_watch_paths:
        return []

    matched_paths = {
        candidate
        for candidate in _git_changed_paths(repo_root.resolve())
        if not _is_ignored_relative_path(candidate)
        if any(
            watch_path_matches(candidate_path=candidate, watch_path=watch_path)
            for watch_path in normalized_watch_paths
        )
    }
    return sorted(matched_paths)


def watch_path_matches(*, candidate_path: str, watch_path: str) -> bool:
    if _is_glob_pattern(watch_path):
        return _matches_glob_pattern(candidate_path=candidate_path, pattern=watch_path)
    return candidate_path == watch_path or candidate_path.startswith(f"{watch_path}/")


def _resolve_files_from_filesystem(
    *,
    capture_root: Path,
    watch_paths: tuple[str, ...],
) -> tuple[Path, ...]:
    resolved_capture_root = capture_root.resolve()
    watched_files: dict[str, Path] = {}
    for watch_path in watch_paths:
        if _is_glob_pattern(watch_path):
            for child in capture_root.glob(watch_path):
                if not child.is_file() or _is_ignored_filesystem_path(child):
                    continue
                resolved_child = child.resolve()
                if not _passes_safety_gates(
                    resolved_child, container=resolved_capture_root
                ):
                    continue
                watched_files[str(resolved_child)] = resolved_child
            continue

        absolute_path = capture_root / watch_path
        if absolute_path.is_file():
            if _is_ignored_filesystem_path(absolute_path):
                continue
            resolved_path = absolute_path.resolve()
            if not _passes_safety_gates(resolved_path, container=resolved_capture_root):
                continue
            watched_files[str(resolved_path)] = resolved_path
            continue
        if absolute_path.is_dir():
            for child in absolute_path.rglob("*"):
                if child.is_file() and not _is_ignored_filesystem_path(child):
                    resolved_child = child.resolve()
                    if not _passes_safety_gates(
                        resolved_child, container=resolved_capture_root
                    ):
                        continue
                    watched_files[str(resolved_child)] = resolved_child

    return tuple(watched_files[key] for key in sorted(watched_files))


def _git_changed_paths(repo_root: Path) -> tuple[str, ...]:
    with Repo(str(repo_root)) as repo:
        status = _status_with_fallback(repo)
        staged_paths = {
            _normalize_repo_path(path)
            for paths in status.staged.values()
            for path in paths
        }
        unstaged_paths = {_normalize_repo_path(path) for path in status.unstaged}
        untracked_paths = {_normalize_repo_path(path) for path in status.untracked}

    return tuple(sorted(staged_paths | unstaged_paths | untracked_paths))


def _status_with_fallback(repo: Repo) -> GitStatus:
    try:
        return porcelain.status(repo, untracked_files="all")
    except OSError:
        return porcelain.status(repo, untracked_files="no")


def _normalize_repo_path(path: bytes | str) -> str:
    if isinstance(path, bytes):
        decoded = path.decode("utf-8", errors="surrogateescape")
    else:
        decoded = path
    return normalize_path(decoded.replace("\\", "/"))


def _is_glob_pattern(path: str) -> bool:
    return any(character in path for character in _GLOB_CHARACTERS)


def _matches_glob_pattern(*, candidate_path: str, pattern: str) -> bool:
    candidate = PurePosixPath(candidate_path)
    return any(candidate.match(variant) for variant in _glob_variants(pattern))


def _glob_variants(pattern: str) -> tuple[str, ...]:
    variants = {pattern}
    pending = [pattern]
    while pending:
        current = pending.pop()
        marker_index = current.find("**/")
        if marker_index == -1:
            continue
        variant = current[:marker_index] + current[marker_index + 3 :]
        if variant in variants:
            continue
        variants.add(variant)
        pending.append(variant)
    return tuple(variants)


def _is_ignored_relative_path(path: str) -> bool:
    return _has_ignored_path_part(PurePosixPath(path).parts)


def _is_ignored_filesystem_path(path: Path) -> bool:
    return _has_ignored_path_part(path.parts)


def _has_ignored_path_part(parts: tuple[str, ...]) -> bool:
    return any(part in _IGNORED_PATH_PARTS for part in parts)


def _passes_safety_gates(resolved_path: Path, *, container: Path) -> bool:
    if not _is_within(resolved_path, container):
        _logger.warning(
            "Skipping watched file outside the configured root: %s",
            resolved_path,
        )
        return False
    if _is_sensitive_file(resolved_path):
        _logger.warning(
            "Skipping watched file with sensitive name: %s",
            resolved_path,
        )
        return False
    return True


def _is_within(child: Path, root: Path) -> bool:
    try:
        return child == root or child.is_relative_to(root)
    except ValueError:
        return False


def _is_sensitive_file(path: Path) -> bool:
    if any(part in _SENSITIVE_PARENT_DIR_PARTS for part in path.parts):
        return True
    name = path.name
    if _FILENAMES_ARE_CASE_INSENSITIVE:
        lowered_name = name.lower()
        return any(
            fnmatch.fnmatchcase(lowered_name, pattern.lower())
            for pattern in _SENSITIVE_FILENAME_PATTERNS
        )
    return any(
        fnmatch.fnmatchcase(name, pattern) for pattern in _SENSITIVE_FILENAME_PATTERNS
    )
