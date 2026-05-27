"""Watched-file capture (target CAPTURE). A read-only orchestrator over the
FileSystem port: it enumerates files under the capture root, keeps only those
matching a watched pattern, drops ignored/sensitive paths, enforces the size
cap, and reads bytes. Contracts C-WATCH-03/05/06/07, C-CONTENT-04, C-WATCH-08."""

from __future__ import annotations

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

if TYPE_CHECKING:
    from collections.abc import Sequence

    from save_my_jupyter.domain.types import RelativeWatchPath
    from save_my_jupyter.ports import FileSystem


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
    for candidate in filesystem.iter_files(capture_root, "**/*"):
        if not is_within_root(candidate, capture_root):
            continue
        relative = candidate.relative_to(capture_root).as_posix()
        relative_pure = PurePosixPath(relative)
        if is_ignored_path(relative_pure) or is_sensitive_file(relative_pure):
            continue
        if not any(
            matches_watch_pattern(candidate=relative, pattern=pattern)
            for pattern in watched_paths
        ):
            continue
        content = filesystem.read_bytes(candidate)
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
        )

    return tuple(collected[key] for key in sorted(collected))
