from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from save_my_jupyter.adapters.activity_sqlite import SqliteActivityStore
from save_my_jupyter.adapters.fake_delivery import FakeDelivery
from save_my_jupyter.application.snapshot.pipeline import (
    PipelineDependencies,
    run_snapshot_pipeline,
)
from save_my_jupyter.domain.config import UserSettingsConfig
from save_my_jupyter.domain.enums import CommitMode, SnapshotSource
from save_my_jupyter.domain.jobs import JobState, RunOutcome
from save_my_jupyter.domain.repo import RepoContext
from save_my_jupyter.domain.requests import (
    NotebookContext,
    RequestedMetadata,
    SnapshotRequest,
)
from save_my_jupyter.domain.types import (
    CellId,
    CommitHash,
    NotebookPath,
    RelativeRepoPath,
    RepoRootPath,
)

_NOW = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)
_ROOT = Path("/repo")


class _FrozenClock:
    def now(self) -> datetime:
        return _NOW


class _FakeGitInspector:
    def __init__(self, context: RepoContext) -> None:
        self._context = context

    def resolve_repo(self, notebook_path: NotebookPath) -> RepoContext:
        del notebook_path
        return self._context


class _RecordingGitMutator:
    def __init__(self) -> None:
        self.committed: list[str] = []

    def stage(
        self, repo_root: RepoRootPath, paths: Sequence[RelativeRepoPath]
    ) -> tuple[RelativeRepoPath, ...]:
        del repo_root
        return tuple(paths)

    def commit(
        self, repo_root: RepoRootPath, *, message: str, current_head: CommitHash | None
    ) -> CommitHash | None:
        del repo_root, current_head
        self.committed.append(message)
        return CommitHash("a" * 40)


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


def _repo_context(*, dirty: bool = False) -> RepoContext:
    return RepoContext(
        repo_root=RepoRootPath(str(_ROOT)),
        relative_notebook_path=RelativeRepoPath("analysis/nb.ipynb"),
        remote_url=None,
        head_commit=CommitHash("b" * 40),
        is_dirty=dirty,
    )


_DEFAULT_CONTENT: Mapping[str, object] = {
    "cells": [{"id": "c1", "source": "# smj: tags=baseline\nx = 1", "outputs": []}],
    "metadata": {},
}


def _default_context() -> NotebookContext:
    return NotebookContext(
        notebook_path=NotebookPath(str(_ROOT / "analysis" / "nb.ipynb")),
        notebook_name="nb.ipynb",
    )


def _request(
    *,
    source: SnapshotSource = SnapshotSource.MANUAL,
    notebook_context: NotebookContext | None = None,
    commit_mode: CommitMode | None = None,
    notebook_content: Mapping[str, object] | None = None,
) -> SnapshotRequest:
    return SnapshotRequest(
        source=source,
        notebook_context=notebook_context or _default_context(),
        metadata=RequestedMetadata(),
        commit_mode=commit_mode,
        notebook_content=notebook_content or _DEFAULT_CONTENT,
    )


def _deps(
    tmp_path: Path, *, mutator: _RecordingGitMutator, dirty: bool
) -> PipelineDependencies:
    return PipelineDependencies(
        git_inspector=_FakeGitInspector(_repo_context(dirty=dirty)),
        git_mutator=mutator,
        filesystem=_MemoryFileSystem({}),
        delivery=FakeDelivery(),
        activity=SqliteActivityStore(tmp_path / "activity.sqlite"),
        clock=_FrozenClock(),
        user_settings=UserSettingsConfig(),
        user_email="a@b.org",
        user_id="user-1",
        extension_version="0.1.0",
    )


def test_manual_snapshot_persists_with_tags_from_directive(tmp_path: Path) -> None:
    deps = _deps(tmp_path, mutator=_RecordingGitMutator(), dirty=False)
    record = run_snapshot_pipeline("job-1", _request(), deps)

    assert record.state is JobState.PERSISTED
    assert record.run_outcome is RunOutcome.NOT_APPLICABLE
    assert record.notebook_path == "analysis/nb.ipynb"
    assert record.page_count == 2  # 00 Metadata + notebook
    assert record.display_message.startswith("Snapshot saved.")


def test_always_commit_mode_commits_when_dirty(tmp_path: Path) -> None:
    mutator = _RecordingGitMutator()
    deps = _deps(tmp_path, mutator=mutator, dirty=True)
    record = run_snapshot_pipeline(
        "job-1", _request(commit_mode=CommitMode.ALWAYS), deps
    )
    assert mutator.committed  # a commit was created
    assert record.commit_hash == "a" * 40


def test_never_commit_mode_reuses_head(tmp_path: Path) -> None:
    mutator = _RecordingGitMutator()
    deps = _deps(tmp_path, mutator=mutator, dirty=True)
    record = run_snapshot_pipeline(
        "job-1", _request(commit_mode=CommitMode.NEVER), deps
    )
    assert mutator.committed == []
    assert record.commit_hash == "b" * 40


def test_trigger_snapshot_records_success_outcome(tmp_path: Path) -> None:
    deps = _deps(tmp_path, mutator=_RecordingGitMutator(), dirty=False)
    request = _request(
        source=SnapshotSource.TRIGGER_CELL,
        notebook_context=NotebookContext(
            notebook_path=NotebookPath(str(_ROOT / "analysis" / "nb.ipynb")),
            notebook_name="nb.ipynb",
            triggering_cell_id=CellId("c1"),
            triggered_cell_ids=(CellId("c1"),),
        ),
    )
    record = run_snapshot_pipeline("job-1", request, deps)
    assert record.state is JobState.PERSISTED
    assert record.run_outcome is RunOutcome.SUCCESS
