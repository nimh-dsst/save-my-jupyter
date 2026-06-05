from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

import pytest
from save_my_jupyter.adapters.activity_sqlite import SqliteActivityStore
from save_my_jupyter.adapters.fake_delivery import FakeDelivery
from save_my_jupyter.application.snapshot.pipeline import (
    PipelineDependencies,
    run_snapshot_pipeline,
)
from save_my_jupyter.domain.config import UserSettingsConfig
from save_my_jupyter.domain.enums import CommitMode, SnapshotSource
from save_my_jupyter.domain.errors import SnapshotError
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
    RelativeWatchPath,
    RepoRootPath,
)

_NOW = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
_ROOT = Path("/repo")


class _FrozenClock:
    def now(self) -> datetime:
        return _NOW


class _FakeGitInspector:
    def __init__(self, context: RepoContext) -> None:
        self._context = context
        self.raw_diff = ""
        self.head_files: dict[str, bytes] = {}

    def resolve_repo(self, notebook_path: NotebookPath) -> RepoContext:
        del notebook_path
        return self._context

    def diff_working_tree(
        self, repo_root: RepoRootPath, paths: Sequence[RelativeRepoPath]
    ) -> str:
        del repo_root, paths
        return self.raw_diff

    def read_head_file(
        self, repo_root: RepoRootPath, path: RelativeRepoPath
    ) -> bytes | None:
        del repo_root
        return self.head_files.get(path)


class _RecordingGitMutator:
    def __init__(self) -> None:
        self.committed: list[str] = []
        self.staged: list[tuple[RelativeRepoPath, ...]] = []

    def stage(
        self, repo_root: RepoRootPath, paths: Sequence[RelativeRepoPath]
    ) -> tuple[RelativeRepoPath, ...]:
        del repo_root
        self.staged.append(tuple(paths))
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
    watched_paths: tuple[RelativeWatchPath, ...] | None = None,
) -> SnapshotRequest:
    return SnapshotRequest(
        source=source,
        notebook_context=notebook_context or _default_context(),
        metadata=RequestedMetadata(),
        commit_mode=commit_mode,
        watched_paths=watched_paths,
        notebook_content=notebook_content or _DEFAULT_CONTENT,
    )


def _deps(
    tmp_path: Path,
    *,
    mutator: _RecordingGitMutator,
    dirty: bool,
    files: dict[Path, bytes] | None = None,
    delivery: FakeDelivery | None = None,
    inspector: _FakeGitInspector | None = None,
) -> PipelineDependencies:
    return PipelineDependencies(
        git_inspector=inspector or _FakeGitInspector(_repo_context(dirty=dirty)),
        git_mutator=mutator,
        filesystem=_MemoryFileSystem(files or {}),
        delivery=delivery or FakeDelivery(),
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


def test_repo_default_tags_merge_into_snapshot_metadata(tmp_path: Path) -> None:
    delivery = FakeDelivery()
    deps = _deps(
        tmp_path,
        mutator=_RecordingGitMutator(),
        dirty=False,
        delivery=delivery,
        files={
            _ROOT / ".save-my-jupyter.toml": (
                b'[defaults]\ndefault_tags = ["repo", "baseline"]\n'
            )
        },
    )

    run_snapshot_pipeline("job-1", _request(), deps)

    assert delivery.delivered[0].metadata.tags == ("baseline", "repo")


def test_user_metadata_extra_fields_override_notebook_defaults(tmp_path: Path) -> None:
    delivery = FakeDelivery()
    deps = _deps(
        tmp_path,
        mutator=_RecordingGitMutator(),
        dirty=False,
        delivery=delivery,
    )
    request = SnapshotRequest(
        source=SnapshotSource.MANUAL,
        notebook_context=_default_context(),
        metadata=RequestedMetadata(extra_fields={"operator": "Ada"}),
        notebook_content={
            "cells": [],
            "metadata": {
                "save_my_jupyter": {
                    "default_metadata": {"operator": "Grace", "sample": "42"}
                }
            },
        },
    )

    run_snapshot_pipeline("job-1", request, deps)

    assert delivery.delivered[0].metadata.extra_fields == {
        "operator": "Ada",
        "sample": "42",
    }


def test_user_default_run_label_is_used_when_request_and_directive_unset(
    tmp_path: Path,
) -> None:
    delivery = FakeDelivery()
    deps = _deps(
        tmp_path,
        mutator=_RecordingGitMutator(),
        dirty=False,
        delivery=delivery,
    )
    deps = PipelineDependencies(
        git_inspector=deps.git_inspector,
        git_mutator=deps.git_mutator,
        filesystem=deps.filesystem,
        delivery=deps.delivery,
        activity=deps.activity,
        clock=deps.clock,
        user_settings=UserSettingsConfig(default_run_label="from-user"),
        user_email=deps.user_email,
        user_id=deps.user_id,
        extension_version=deps.extension_version,
    )

    run_snapshot_pipeline(
        "job-1",
        _request(notebook_content={"cells": [], "metadata": {}}),
        deps,
    )

    assert delivery.delivered[0].metadata.run_label == "from-user"


def test_always_commit_mode_commits_when_dirty(tmp_path: Path) -> None:
    mutator = _RecordingGitMutator()
    deps = _deps(tmp_path, mutator=mutator, dirty=True)
    record = run_snapshot_pipeline(
        "job-1", _request(commit_mode=CommitMode.ALWAYS), deps
    )
    assert mutator.committed  # a commit was created
    assert record.commit_hash == "a" * 40


def test_commit_respects_disabled_notebook_staging_but_stages_repo_config(
    tmp_path: Path,
) -> None:
    mutator = _RecordingGitMutator()
    deps = _deps(
        tmp_path,
        mutator=mutator,
        dirty=True,
        files={
            _ROOT
            / ".save-my-jupyter.toml": b"[git]\nstage_notebook_on_commit = false\n"
        },
    )
    record = run_snapshot_pipeline(
        "job-1", _request(commit_mode=CommitMode.ALWAYS), deps
    )

    assert mutator.staged == [(RelativeRepoPath(".save-my-jupyter.toml"),)]
    assert mutator.committed
    assert record.commit_hash == "a" * 40


def test_never_commit_mode_reuses_head(tmp_path: Path) -> None:
    mutator = _RecordingGitMutator()
    deps = _deps(tmp_path, mutator=mutator, dirty=True)
    record = run_snapshot_pipeline(
        "job-1", _request(commit_mode=CommitMode.NEVER), deps
    )
    assert mutator.committed == []
    assert record.commit_hash == "b" * 40


def test_dirty_never_commit_snapshot_includes_filtered_diff(tmp_path: Path) -> None:
    delivery = FakeDelivery()
    inspector = _FakeGitInspector(_repo_context(dirty=True))
    deps = _deps(
        tmp_path,
        mutator=_RecordingGitMutator(),
        dirty=True,
        delivery=delivery,
        inspector=inspector,
        files={
            _ROOT
            / ".save-my-jupyter.toml": b'[defaults]\nwatch_paths = ["results.csv"]\n',
            _ROOT / "results.csv": b"new",
        },
    )
    inspector.raw_diff = (
        "diff --git a/analysis/nb.ipynb b/analysis/nb.ipynb\n"
        "--- a/analysis/nb.ipynb\n+++ b/analysis/nb.ipynb\n@@ -1 +1 @@\n-{}\n+{}\n\n"
        "diff --git a/results.csv b/results.csv\n"
        "--- a/results.csv\n+++ b/results.csv\n@@ -1 +1 @@\n-old\n+new"
    )

    record = run_snapshot_pipeline(
        "job-1", _request(commit_mode=CommitMode.NEVER), deps
    )

    assert record.page_count == 4
    bundle = delivery.delivered[0]
    assert bundle.metadata.diff_included is True
    assert bundle.metadata.working_tree_diff is not None
    assert "results.csv" in bundle.metadata.working_tree_diff
    diff_artifact = bundle.artifacts[-1]
    assert diff_artifact.page_name == "working-tree.patch"
    assert b"results.csv" in diff_artifact.content
    assert b"analysis/nb.ipynb" not in diff_artifact.content


def test_request_watched_paths_are_captured(tmp_path: Path) -> None:
    delivery = FakeDelivery()
    deps = _deps(
        tmp_path,
        mutator=_RecordingGitMutator(),
        dirty=False,
        delivery=delivery,
        files={_ROOT / "outputs" / "result.csv": b"a,b"},
    )

    run_snapshot_pipeline(
        "job-1",
        _request(watched_paths=(RelativeWatchPath("outputs"),)),
        deps,
    )

    artifacts = delivery.delivered[0].artifacts
    page_names = [artifact.page_name for artifact in artifacts]
    assert "result.csv" in page_names
    assert "outputs/result.csv" in [artifact.relative_path for artifact in artifacts]


def test_non_git_project_config_is_loaded_from_project_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    notebook_path = root / "analysis" / "nb.ipynb"
    delivery = FakeDelivery()
    deps = _deps(
        tmp_path,
        mutator=_RecordingGitMutator(),
        dirty=False,
        delivery=delivery,
        inspector=_FakeGitInspector(
            RepoContext(
                repo_root=None,
                relative_notebook_path=None,
                remote_url=None,
                head_commit=None,
                is_dirty=False,
            )
        ),
        files={
            root / "pyproject.toml": b"[project]\nname = 'demo'\n",
            root / ".save-my-jupyter.toml": b"[defaults]\nwatch_paths = ['outputs']\n",
            root / "outputs" / "result.csv": b"a,b",
        },
    )

    run_snapshot_pipeline(
        "job-1",
        _request(
            notebook_context=NotebookContext(
                notebook_path=NotebookPath(str(notebook_path)),
                notebook_name="nb.ipynb",
            )
        ),
        deps,
    )

    artifacts = delivery.delivered[0].artifacts
    page_names = [artifact.page_name for artifact in artifacts]
    assert "result.csv" in page_names
    assert "outputs/result.csv" in [artifact.relative_path for artifact in artifacts]


def test_sensitive_watched_files_are_not_staged_for_snapshot_commit(
    tmp_path: Path,
) -> None:
    mutator = _RecordingGitMutator()
    delivery = FakeDelivery()
    deps = _deps(
        tmp_path,
        mutator=mutator,
        dirty=True,
        delivery=delivery,
        files={
            _ROOT / ".save-my-jupyter.toml": (
                b"[defaults]\n"
                b'watch_paths = ["outputs", "secrets"]\n'
                b"[git]\n"
                b"stage_notebook_on_commit = false\n"
                b"stage_watched_paths_on_commit = true\n"
            ),
            _ROOT / "outputs" / "result.csv": b"a,b",
            _ROOT / "secrets" / ".env": b"SECRET=1",
        },
    )

    record = run_snapshot_pipeline(
        "job-1", _request(commit_mode=CommitMode.ALWAYS), deps
    )

    assert record.state is JobState.PERSISTED
    assert mutator.staged == [
        (
            RelativeRepoPath("outputs/result.csv"),
            RelativeRepoPath(".save-my-jupyter.toml"),
        )
    ]
    artifacts = delivery.delivered[0].artifacts
    page_names = [artifact.page_name for artifact in artifacts]
    assert "result.csv" in page_names
    assert "outputs/result.csv" in [artifact.relative_path for artifact in artifacts]
    assert ".env" not in page_names


def test_snapshot_metadata_includes_noise_filtered_notebook_diff(
    tmp_path: Path,
) -> None:
    delivery = FakeDelivery()
    inspector = _FakeGitInspector(_repo_context(dirty=True))
    deps = _deps(
        tmp_path,
        mutator=_RecordingGitMutator(),
        dirty=True,
        delivery=delivery,
        inspector=inspector,
    )
    inspector.head_files["analysis/nb.ipynb"] = (
        b'{"cells": [{"cell_type": "code", "source": "x = 1\\n", "outputs": []}]}'
    )

    run_snapshot_pipeline(
        "job-1",
        _request(
            commit_mode=CommitMode.NEVER,
            notebook_content={
                "cells": [{"cell_type": "code", "source": "x = 2\n", "outputs": []}]
            },
        ),
        deps,
    )

    diff = delivery.delivered[0].metadata.notebook_diff
    assert diff is not None
    assert diff.page_name == "01 Notebook Diff"
    assert diff.summary == "1 of 1 cells changed."
    assert "-x = 1" in diff.entries[0].html
    assert "+x = 2" in diff.entries[0].html


def test_trigger_snapshot_records_success_outcome(tmp_path: Path) -> None:
    delivery = FakeDelivery()
    deps = _deps(
        tmp_path, mutator=_RecordingGitMutator(), dirty=False, delivery=delivery
    )
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
    assert delivery.delivered[0].metadata.run_fingerprint is not None


def test_trigger_snapshot_records_error_outcome(tmp_path: Path) -> None:
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
    request = SnapshotRequest(
        source=request.source,
        notebook_context=request.notebook_context,
        metadata=request.metadata,
        run_outcome=RunOutcome.ERROR,
        notebook_content=request.notebook_content,
    )

    record = run_snapshot_pipeline("job-1", request, deps)

    assert record.state is JobState.PERSISTED
    assert record.run_outcome is RunOutcome.ERROR


def test_oversized_notebook_payload_fails_before_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from save_my_jupyter.application.snapshot import pipeline

    monkeypatch.setattr(pipeline, "NOTEBOOK_MAX_BYTES", 10)
    deps = _deps(tmp_path, mutator=_RecordingGitMutator(), dirty=False)

    with pytest.raises(SnapshotError) as exc:
        run_snapshot_pipeline(
            "job-1",
            _request(notebook_content={"cells": [], "metadata": {"large": "x" * 100}}),
            deps,
        )

    assert exc.value.code == "notebook_artifact_too_large"
