from __future__ import annotations

import base64
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from save_my_jupyter.domain import (
    CellId,
    CommitMode,
    DocumentId,
    EffectiveConfig,
    KernelId,
    LabArchivesNotebookName,
    LabArchivesRootPath,
    LabArchivesTarget,
    ManualSnapshotRequest,
    NotebookContext,
    NotebookPath,
    RelativeWatchPath,
    ResolvedRepoContext,
    ResolvedSnapshotPlan,
    RunFingerprint,
    TriggerCellSnapshotRequest,
    UserMetadata,
)
from save_my_jupyter.git import parse_commit_hash, parse_git_remote
from save_my_jupyter.services.artifacts import DocumentArtifactCollector
from save_my_jupyter.services.coordinator import SnapshotCoordinator
from save_my_jupyter.services.run_fingerprint import RunFingerprintService


def _artifact_plan(
    notebook_path: Path,
    *,
    request: ManualSnapshotRequest | None = None,
    watched_paths: tuple[RelativeWatchPath, ...] = (),
) -> ResolvedSnapshotPlan:
    resolved_request = request
    if resolved_request is None:
        resolved_request = ManualSnapshotRequest(
            notebook_context=NotebookContext(
                notebook_path=NotebookPath(str(notebook_path)),
                notebook_name=notebook_path.name,
            ),
            commit_mode=CommitMode.NEVER,
            user_metadata=UserMetadata(),
        )

    return ResolvedSnapshotPlan(
        request=resolved_request,
        repo=ResolvedRepoContext(
            repo_root=None,
            relative_notebook_path=None,
            remote_url=None,
            head_commit=None,
            is_dirty=False,
        ),
        effective_config=EffectiveConfig(
            all_cells_trigger=False,
            commit_mode=CommitMode.NEVER,
            watched_paths=watched_paths,
            include_notebook_file=True,
            include_diff_when_dirty=True,
            target=LabArchivesTarget(
                notebook_name=LabArchivesNotebookName("Snapshots"),
                root_path=LabArchivesRootPath("Runs"),
            ),
            metadata_template={},
            stage_notebook_on_commit=True,
            stage_watched_paths_on_commit=False,
            commit_message_template="snapshot",
        ),
        run_fingerprint=RunFingerprint("fingerprint-2"),
    )


def test_parse_git_helpers() -> None:
    remote = parse_git_remote("git@github.com:example/repo.git")
    assert str(remote) == "git@github.com:example/repo.git"
    assert parse_commit_hash("abc1234") == "abc1234"
    assert parse_commit_hash("not-a-hash") is None


def test_run_fingerprint_distinguishes_executions_of_same_cell() -> None:
    timestamp = datetime(2026, 4, 10, 12, 30, tzinfo=UTC)
    first = TriggerCellSnapshotRequest(
        notebook_context=NotebookContext(
            notebook_path=NotebookPath("C:/repo/notebook.ipynb"),
            notebook_name="notebook.ipynb",
            document_id=DocumentId("doc-1"),
            kernel_id=KernelId("kernel-1"),
            triggering_cell_id=CellId("cell-1"),
            cell_execution_count=1,
        ),
        commit_mode=CommitMode.PROMPT,
        user_metadata=UserMetadata(),
        client_timestamp=timestamp,
    )
    second = TriggerCellSnapshotRequest(
        notebook_context=NotebookContext(
            notebook_path=NotebookPath("C:/repo/notebook.ipynb"),
            notebook_name="notebook.ipynb",
            document_id=DocumentId("doc-1"),
            kernel_id=KernelId("kernel-1"),
            triggering_cell_id=CellId("cell-1"),
            cell_execution_count=2,
        ),
        commit_mode=CommitMode.PROMPT,
        user_metadata=UserMetadata(),
        client_timestamp=timestamp,
    )
    service = RunFingerprintService()
    assert service.compute(first) != service.compute(second)


def test_run_fingerprint_distinguishes_different_trigger_cells() -> None:
    timestamp = datetime(2026, 4, 10, 12, 30, tzinfo=UTC)
    first = TriggerCellSnapshotRequest(
        notebook_context=NotebookContext(
            notebook_path=NotebookPath("C:/repo/notebook.ipynb"),
            notebook_name="notebook.ipynb",
            document_id=DocumentId("doc-1"),
            kernel_id=KernelId("kernel-1"),
            triggering_cell_id=CellId("cell-1"),
            cell_execution_count=1,
        ),
        commit_mode=CommitMode.PROMPT,
        user_metadata=UserMetadata(),
        client_timestamp=timestamp,
    )
    second = TriggerCellSnapshotRequest(
        notebook_context=NotebookContext(
            notebook_path=NotebookPath("C:/repo/notebook.ipynb"),
            notebook_name="notebook.ipynb",
            document_id=DocumentId("doc-1"),
            kernel_id=KernelId("kernel-1"),
            triggering_cell_id=CellId("cell-2"),
            cell_execution_count=1,
        ),
        commit_mode=CommitMode.PROMPT,
        user_metadata=UserMetadata(),
        client_timestamp=timestamp,
    )
    service = RunFingerprintService()
    assert service.compute(first) != service.compute(second)


def test_run_fingerprint_dedupes_duplicate_trigger_events() -> None:
    context = NotebookContext(
        notebook_path=NotebookPath("C:/repo/notebook.ipynb"),
        notebook_name="notebook.ipynb",
        document_id=DocumentId("doc-1"),
        kernel_id=KernelId("kernel-1"),
        triggering_cell_id=CellId("cell-1"),
        cell_execution_count=1,
    )
    first = TriggerCellSnapshotRequest(
        notebook_context=context,
        commit_mode=CommitMode.PROMPT,
        user_metadata=UserMetadata(),
        client_timestamp=datetime(2026, 4, 10, 12, 30, tzinfo=UTC),
    )
    second = TriggerCellSnapshotRequest(
        notebook_context=context,
        commit_mode=CommitMode.PROMPT,
        user_metadata=UserMetadata(),
        client_timestamp=datetime(2026, 4, 10, 12, 30, 5, tzinfo=UTC),
    )
    service = RunFingerprintService()
    assert service.compute(first) == service.compute(second)


def test_run_fingerprint_service_is_stable() -> None:
    request = ManualSnapshotRequest(
        notebook_context=NotebookContext(
            notebook_path=NotebookPath("C:/repo/notebook.ipynb"),
            notebook_name="notebook.ipynb",
            document_id=DocumentId("doc-1"),
            kernel_id=KernelId("kernel-1"),
        ),
        commit_mode=CommitMode.PROMPT,
        user_metadata=UserMetadata(),
        client_timestamp=datetime(2026, 4, 10, 12, 30, tzinfo=UTC),
    )
    service = RunFingerprintService()

    assert service.compute(request) == service.compute(request)


def test_snapshot_coordinator_dedupes_same_run() -> None:
    request = ManualSnapshotRequest(
        notebook_context=NotebookContext(
            notebook_path=NotebookPath("C:/repo/notebook.ipynb"),
            notebook_name="notebook.ipynb",
        ),
        commit_mode=CommitMode.PROMPT,
        user_metadata=UserMetadata(),
    )
    plan = ResolvedSnapshotPlan(
        request=request,
        repo=ResolvedRepoContext(
            repo_root=None,
            relative_notebook_path=None,
            remote_url=None,
            head_commit=None,
            is_dirty=False,
        ),
        effective_config=EffectiveConfig(
            all_cells_trigger=False,
            commit_mode=CommitMode.PROMPT,
            watched_paths=(),
            include_notebook_file=True,
            include_diff_when_dirty=True,
            target=LabArchivesTarget(
                notebook_name=LabArchivesNotebookName("Snapshots"),
                root_path=LabArchivesRootPath("Runs"),
            ),
            metadata_template={},
            stage_notebook_on_commit=True,
            stage_watched_paths_on_commit=False,
            commit_message_template="snapshot",
        ),
        run_fingerprint=RunFingerprint("fingerprint-1"),
    )
    coordinator = SnapshotCoordinator()

    first_result = coordinator.submit(plan)
    assert first_result.status == "accepted"
    queue = coordinator.get_or_create_queue(
        coordinator.build_notebook_key(plan.request.notebook_context)
    )
    queue.mark_complete(RunFingerprint("fingerprint-1"))

    trigger_request = TriggerCellSnapshotRequest(
        notebook_context=NotebookContext(
            notebook_path=NotebookPath("C:/repo/notebook.ipynb"),
            notebook_name="notebook.ipynb",
            triggering_cell_id=CellId("cell-1"),
        ),
        commit_mode=CommitMode.PROMPT,
        user_metadata=UserMetadata(),
        client_timestamp=request.client_timestamp,
    )
    trigger_plan = ResolvedSnapshotPlan(
        request=trigger_request,
        repo=plan.repo,
        effective_config=plan.effective_config,
        run_fingerprint=RunFingerprint("fingerprint-1"),
    )

    second_result = coordinator.submit(trigger_plan)
    assert second_result.status == "rejected"


def test_snapshot_queue_can_clear_running_job_without_recording_run() -> None:
    request = ManualSnapshotRequest(
        notebook_context=NotebookContext(
            notebook_path=NotebookPath("C:/repo/notebook.ipynb"),
            notebook_name="notebook.ipynb",
        ),
        commit_mode=CommitMode.PROMPT,
        user_metadata=UserMetadata(),
    )
    plan = ResolvedSnapshotPlan(
        request=request,
        repo=ResolvedRepoContext(
            repo_root=None,
            relative_notebook_path=None,
            remote_url=None,
            head_commit=None,
            is_dirty=False,
        ),
        effective_config=EffectiveConfig(
            all_cells_trigger=False,
            commit_mode=CommitMode.PROMPT,
            watched_paths=(),
            include_notebook_file=True,
            include_diff_when_dirty=True,
            target=LabArchivesTarget(
                notebook_name=LabArchivesNotebookName("Snapshots"),
                root_path=LabArchivesRootPath("Runs"),
            ),
            metadata_template={},
            stage_notebook_on_commit=True,
            stage_watched_paths_on_commit=False,
            commit_message_template="snapshot",
        ),
        run_fingerprint=RunFingerprint("fingerprint-3"),
    )
    coordinator = SnapshotCoordinator()
    queue = coordinator.get_or_create_queue(
        coordinator.build_notebook_key(plan.request.notebook_context)
    )
    queue.enqueue(plan)

    started_plan = queue.start_next()
    assert started_plan is not None
    assert queue.running_job is started_plan

    queue.mark_finished(started_plan.run_fingerprint, record_run=False)

    assert queue.running_job is None
    assert queue.has_seen_run(started_plan.run_fingerprint) is False


def test_document_artifact_collector_collects_figures_and_summary() -> None:
    test_root = Path.cwd() / ".test_artifact_repo"
    shutil.rmtree(test_root, ignore_errors=True)
    test_root.mkdir(parents=True, exist_ok=True)
    try:
        notebook_path = test_root / "example.ipynb"
        notebook_path.write_text(
            json.dumps(
                {
                    "cells": [
                        {
                            "cell_type": "code",
                            "id": "cell-a",
                            "outputs": [
                                {
                                    "data": {
                                        "image/png": base64.b64encode(
                                            b"png-bytes"
                                        ).decode("utf-8"),
                                        "text/plain": "42",
                                    }
                                },
                                {
                                    "data": {
                                        "image/svg+xml": [
                                            '<svg xmlns="http://www.w3.org/2000/svg">',
                                            '<rect width="10" height="10" />',
                                            "</svg>",
                                        ]
                                    }
                                },
                                {
                                    "output_type": "stream",
                                    "text": "stream output",
                                },
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        plan = _artifact_plan(notebook_path)

        collector = DocumentArtifactCollector()
        figures = collector.collect_figure_artifacts(plan)
        summary = collector.collect_value_summary(plan)

        assert len(figures) == 2
        assert figures[0].display_name == "figure-cell-a-output-01.png"
        assert figures[0].bytes_payload == b"png-bytes"
        assert str(figures[0].mime_type) == "image/png"
        assert figures[1].display_name == "figure-cell-a-output-02.svg"
        assert figures[1].bytes_payload.startswith(b"<svg")
        assert str(figures[1].mime_type) == "image/svg+xml"
        assert summary is not None
        assert "Result Summary" in summary
        assert "Cell        : Cell 1 (id: cell-a)" in summary
        assert "Output      : 1" in summary
        assert "Output type : (unknown)" in summary
        assert 'Source      : data["text/plain"]' in summary
        assert "42" in summary
        assert "Image output: image/svg+xml" in summary
        assert "stream output" in summary
    finally:
        shutil.rmtree(test_root, ignore_errors=True)


def test_document_artifact_collector_collects_watched_files() -> None:
    test_root = Path.cwd() / ".test_artifact_watch_repo"
    shutil.rmtree(test_root, ignore_errors=True)
    test_root.mkdir(parents=True, exist_ok=True)
    try:
        notebook_path = test_root / "example.ipynb"
        notebook_path.write_text('{"cells":[]}', encoding="utf-8")
        outputs_root = test_root / "outputs"
        outputs_root.mkdir()
        csv_path = outputs_root / "result.csv"
        csv_path.write_text("value\n1\n", encoding="utf-8")
        png_path = outputs_root / "figure.png"
        png_path.write_bytes(b"\x89PNG\r\n\x1a\n")

        plan = _artifact_plan(
            notebook_path,
            watched_paths=(RelativeWatchPath("outputs"),),
        )

        collector = DocumentArtifactCollector()
        file_artifacts = collector.collect_file_artifacts(plan)

        assert [artifact.display_name for artifact in file_artifacts] == [
            "figure.png",
            "result.csv",
        ]
        assert [str(artifact.relative_path) for artifact in file_artifacts] == [
            "outputs/figure.png",
            "outputs/result.csv",
        ]
        assert [str(artifact.mime_type) for artifact in file_artifacts] == [
            "image/png",
            "text/csv",
        ]
        assert [artifact.bytes_payload for artifact in file_artifacts] == [
            b"\x89PNG\r\n\x1a\n",
            csv_path.read_bytes(),
        ]
    finally:
        shutil.rmtree(test_root, ignore_errors=True)


def test_document_artifact_collector_ignores_ipynb_checkpoints() -> None:
    test_root = Path.cwd() / ".test_artifact_checkpoint_repo"
    shutil.rmtree(test_root, ignore_errors=True)
    test_root.mkdir(parents=True, exist_ok=True)
    try:
        notebook_path = test_root / "example.ipynb"
        notebook_path.write_text('{"cells":[]}', encoding="utf-8")
        outputs_root = test_root / "outputs"
        outputs_root.mkdir()
        checkpoint_root = outputs_root / ".ipynb_checkpoints"
        checkpoint_root.mkdir()
        kept_path = outputs_root / "result.csv"
        kept_path.write_text("value\n1\n", encoding="utf-8")
        ignored_path = checkpoint_root / "result-checkpoint.csv"
        ignored_path.write_text("value\n0\n", encoding="utf-8")

        plan = _artifact_plan(
            notebook_path,
            watched_paths=(RelativeWatchPath("outputs"),),
        )

        collector = DocumentArtifactCollector()
        file_artifacts = collector.collect_file_artifacts(plan)

        assert [artifact.display_name for artifact in file_artifacts] == ["result.csv"]
        assert [str(artifact.relative_path) for artifact in file_artifacts] == [
            "outputs/result.csv"
        ]
    finally:
        shutil.rmtree(test_root, ignore_errors=True)


def test_document_artifact_collector_skips_sensitive_watched_files() -> None:
    test_root = Path.cwd() / ".test_artifact_sensitive_repo"
    shutil.rmtree(test_root, ignore_errors=True)
    test_root.mkdir(parents=True, exist_ok=True)
    try:
        notebook_path = test_root / "example.ipynb"
        notebook_path.write_text('{"cells":[]}', encoding="utf-8")
        kept_path = test_root / "result.csv"
        kept_path.write_text("value\n1\n", encoding="utf-8")
        (test_root / ".env").write_text("SECRET=1\n", encoding="utf-8")
        ssh_dir = test_root / ".ssh"
        ssh_dir.mkdir()
        (ssh_dir / "id_rsa").write_text("private", encoding="utf-8")
        cache_dir = test_root / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "module.cpython-312.pyc").write_bytes(b"\x00")

        plan = _artifact_plan(
            notebook_path,
            watched_paths=(RelativeWatchPath("**/*"),),
        )

        collector = DocumentArtifactCollector()
        file_artifacts = collector.collect_file_artifacts(plan)

        artifact_names = [artifact.display_name for artifact in file_artifacts]
        assert "result.csv" in artifact_names
        assert ".env" not in artifact_names
        assert "id_rsa" not in artifact_names
        assert "module.cpython-312.pyc" not in artifact_names
    finally:
        shutil.rmtree(test_root, ignore_errors=True)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Symlink creation typically requires admin privileges on Windows.",
)
def test_document_artifact_collector_drops_symlink_escaping_capture_root() -> None:
    test_root = Path.cwd() / ".test_artifact_symlink_repo"
    outside_root = Path.cwd() / ".test_artifact_symlink_outside"
    shutil.rmtree(test_root, ignore_errors=True)
    shutil.rmtree(outside_root, ignore_errors=True)
    test_root.mkdir(parents=True, exist_ok=True)
    outside_root.mkdir(parents=True, exist_ok=True)
    try:
        notebook_path = test_root / "example.ipynb"
        notebook_path.write_text('{"cells":[]}', encoding="utf-8")
        kept_path = test_root / "kept.csv"
        kept_path.write_text("value\n1\n", encoding="utf-8")
        secret_path = outside_root / "secret.txt"
        secret_path.write_text("private", encoding="utf-8")
        symlink_path = test_root / "escape.txt"
        symlink_path.symlink_to(secret_path)

        plan = _artifact_plan(
            notebook_path,
            watched_paths=(RelativeWatchPath("**/*"),),
        )

        collector = DocumentArtifactCollector()
        file_artifacts = collector.collect_file_artifacts(plan)

        artifact_names = [artifact.display_name for artifact in file_artifacts]
        assert "kept.csv" in artifact_names
        assert "escape.txt" not in artifact_names
        assert "secret.txt" not in artifact_names
    finally:
        shutil.rmtree(test_root, ignore_errors=True)
        shutil.rmtree(outside_root, ignore_errors=True)
