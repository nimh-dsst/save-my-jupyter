"""Watched-file capture (target CAPTURE). A read-only orchestrator over the
FileSystem port: it enumerates files under the capture root, keeps only those
matching a watched pattern, drops ignored/sensitive paths, enforces the size
cap, and reads bytes. Contracts C-WATCH-03/05/06/07, C-CONTENT-04, C-WATCH-08."""

from __future__ import annotations

import logging
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from save_my_jupyter.application.snapshot.guards import (
    WATCHED_FILE_MAX_BYTES,
    enforce_size_cap,
    is_ignored_path,
    is_sensitive_file,
    is_within_root,
    matches_watch_pattern,
)
from save_my_jupyter.application.snapshot.notebook_content import (
    resolve_artifact_mime_type,
)
from save_my_jupyter.domain.artifacts import WatchedFileArtifact
from save_my_jupyter.domain.errors import SnapshotError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from save_my_jupyter.domain.types import RelativeWatchPath
    from save_my_jupyter.ports import FileSystem

_LOG = logging.getLogger(__name__)


def gather_watched_files(
    *,
    watched_paths: Sequence[RelativeWatchPath],
    capture_root: Path,
    filesystem: FileSystem,
    max_file_bytes: int = WATCHED_FILE_MAX_BYTES,
) -> tuple[WatchedFileArtifact, ...]:
    if not watched_paths:
        return ()

    collected: dict[str, WatchedFileArtifact] = {}
    resolved_root = capture_root.resolve()
    for candidate in filesystem.iter_files(capture_root, "**/*"):
        try:
            resolved_candidate = candidate.resolve()
        except OSError as exc:
            _LOG.warning(
                "Save My Jupyter skipped watched file because its path could not "
                "be resolved: path=%s error=%s",
                candidate,
                exc,
            )
            continue
        if not is_within_root(resolved_candidate, resolved_root):
            _LOG.warning(
                "Save My Jupyter skipped watched file outside capture root: "
                "path=%s resolved_path=%s root=%s",
                candidate,
                resolved_candidate,
                resolved_root,
            )
            continue
        try:
            relative = candidate.relative_to(capture_root).as_posix()
        except ValueError:
            _LOG.warning(
                "Save My Jupyter skipped watched file outside capture root: "
                "path=%s root=%s",
                candidate,
                capture_root,
            )
            continue
        relative_pure = PurePosixPath(relative)
        if is_ignored_path(relative_pure):
            continue
        if is_sensitive_file(relative_pure):
            _LOG.warning(
                "Save My Jupyter skipped sensitive watched file: path=%s",
                candidate,
            )
            continue
        if not any(
            matches_watch_pattern(candidate=relative, pattern=pattern)
            for pattern in watched_paths
        ):
            continue
        try:
            content = filesystem.read_bytes(candidate)
        except OSError as exc:
            raise SnapshotError(
                "Unable to read watched file artifact.",
                code="watched_file_artifact_read_failed",
                context={"path": str(candidate)},
            ) from exc
        enforce_size_cap(
            size_bytes=len(content),
            max_bytes=max_file_bytes,
            code="watched_file_artifact_too_large",
            path=candidate,
        )
        collected[relative] = WatchedFileArtifact(
            filename=candidate.name,
            mime_type=resolve_artifact_mime_type(candidate.name),
            content=content,
            relative_path=relative,
        )

    return tuple(collected[key] for key in sorted(collected))
