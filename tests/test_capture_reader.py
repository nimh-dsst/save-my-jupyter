from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from save_my_jupyter.application.snapshot.capture_reader import gather_watched_files
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.domain.types import RelativeWatchPath

if TYPE_CHECKING:
    from save_my_jupyter.domain.artifacts import WatchedFileArtifact

_ROOT = Path("/repo")


class _MemoryFileSystem:
    def __init__(self, files: dict[Path, bytes]) -> None:
        self._files = files

    def exists(self, path: Path) -> bool:
        return path in self._files

    def is_file(self, path: Path) -> bool:
        return path in self._files

    def read_bytes(self, path: Path) -> bytes:
        return self._files[path]

    def iter_files(self, root: Path, pattern: str) -> Iterator[Path]:
        del pattern
        for candidate in self._files:
            if candidate == root or root in candidate.parents:
                yield candidate


def _filesystem(relative_files: dict[str, bytes]) -> _MemoryFileSystem:
    return _MemoryFileSystem(
        {_ROOT / name: content for name, content in relative_files.items()}
    )


def _names(artifacts: Sequence[WatchedFileArtifact]) -> list[str]:
    return [artifact.filename for artifact in artifacts]


def test_no_watched_paths_collects_nothing() -> None:
    filesystem = _filesystem({"outputs/a.csv": b"x"})
    assert (
        gather_watched_files(
            watched_paths=(), capture_root=_ROOT, filesystem=filesystem
        )
        == ()
    )


def test_directory_pattern_collects_files_beneath_it() -> None:
    filesystem = _filesystem(
        {"outputs/a.csv": b"a,b", "outputs/sub/b.json": b"{}", "other/c.txt": b"c"}
    )
    artifacts = gather_watched_files(
        watched_paths=(RelativeWatchPath("outputs"),),
        capture_root=_ROOT,
        filesystem=filesystem,
    )
    assert _names(artifacts) == ["a.csv", "b.json"]
    assert [artifact.relative_path for artifact in artifacts] == [
        "outputs/a.csv",
        "outputs/sub/b.json",
    ]


def test_glob_pattern_matches_by_extension() -> None:
    filesystem = _filesystem({"a.csv": b"x", "b.json": b"{}", "c.csv": b"y"})
    artifacts = gather_watched_files(
        watched_paths=(RelativeWatchPath("**/*.csv"),),
        capture_root=_ROOT,
        filesystem=filesystem,
    )
    assert _names(artifacts) == ["a.csv", "c.csv"]


def test_mime_type_resolved_from_extension() -> None:
    filesystem = _filesystem({"outputs/a.csv": b"x"})
    artifact = gather_watched_files(
        watched_paths=(RelativeWatchPath("outputs"),),
        capture_root=_ROOT,
        filesystem=filesystem,
    )[0]
    assert artifact.mime_type == "text/csv"
    assert artifact.content == b"x"


def test_sensitive_files_are_excluded(caplog: pytest.LogCaptureFixture) -> None:
    filesystem = _filesystem({"secrets/.env": b"SECRET=1", "secrets/ok.csv": b"x"})
    caplog.set_level(logging.WARNING)
    artifacts = gather_watched_files(
        watched_paths=(RelativeWatchPath("secrets"),),
        capture_root=_ROOT,
        filesystem=filesystem,
    )
    assert _names(artifacts) == ["ok.csv"]
    assert "skipped sensitive tracked file" in caplog.text


def test_ignored_directories_are_excluded() -> None:
    filesystem = _filesystem(
        {
            "__pycache__/m.pyc": b"x",
            ".ipynb_checkpoints/n.ipynb": b"{}",
            "keep.csv": b"y",
        }
    )
    artifacts = gather_watched_files(
        watched_paths=(RelativeWatchPath("**/*"),),
        capture_root=_ROOT,
        filesystem=filesystem,
    )
    assert _names(artifacts) == ["keep.csv"]


def test_file_over_size_cap_raises() -> None:
    filesystem = _filesystem({"outputs/big.csv": b"x" * 50})
    with pytest.raises(SnapshotError) as exc:
        gather_watched_files(
            watched_paths=(RelativeWatchPath("outputs"),),
            capture_root=_ROOT,
            filesystem=filesystem,
            max_file_bytes=10,
        )
    assert exc.value.code == "watched_file_artifact_too_large"


def test_symlink_to_file_outside_root_is_dropped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    root = tmp_path / "repo"
    root.mkdir()
    link = root / "outputs.txt"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    caplog.set_level(logging.WARNING)
    artifacts = gather_watched_files(
        watched_paths=(RelativeWatchPath("**/*.txt"),),
        capture_root=root,
        filesystem=_PathFileSystem(),
    )

    assert artifacts == ()
    assert "skipped tracked file outside capture root" in caplog.text


class _PathFileSystem:
    def exists(self, path: Path) -> bool:
        return path.exists()

    def is_file(self, path: Path) -> bool:
        return path.is_file()

    def read_bytes(self, path: Path) -> bytes:
        return path.read_bytes()

    def iter_files(self, root: Path, pattern: str) -> Iterator[Path]:
        yield from root.glob(pattern)
