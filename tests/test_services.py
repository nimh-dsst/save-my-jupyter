from __future__ import annotations

import base64
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

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
from save_my_jupyter.git.parsers import parse_commit_hash, parse_git_remote
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
        path_rule=None,
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
        path_rule=None,
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
        path_rule=None,
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
        path_rule=None,
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
                                            "<svg xmlns=\"http://www.w3.org/2000/svg\">",
                                            "<rect width=\"10\" height=\"10\" />",
                                            "</svg>",
                                        ]
                                    }
                                },
                                {
                                    "output_type": "stream",
                                    "text": "stream output",
                                }
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
        assert figures[0].bytes_payload == b"png-bytes"
        assert str(figures[0].mime_type) == "image/png"
        assert figures[1].bytes_payload.startswith(b"<svg")
        assert str(figures[1].mime_type) == "image/svg+xml"
        assert summary == "42"
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
    finally:
        shutil.rmtree(test_root, ignore_errors=True)
