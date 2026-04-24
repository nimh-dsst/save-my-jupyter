from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from save_my_jupyter.adapters.labarchives import LabArchivesAdapter
from save_my_jupyter.config.service import ConfigService
from save_my_jupyter.domain import (
    ArtifactKind,
    CellId,
    CommitMode,
    ManualSnapshotRequest,
    NotebookContext,
    NotebookPath,
    SnapshotSource,
    TriggerCellSnapshotRequest,
    UserId,
    UserMetadata,
)
from save_my_jupyter.git.service import DefaultGitService
from save_my_jupyter.services.artifacts import DocumentArtifactCollector
from save_my_jupyter.services.auth import AuthServiceImpl
from save_my_jupyter.services.run_fingerprint import RunFingerprintService
from save_my_jupyter.services.snapshot import SnapshotService


def test_execute_snapshot_records_dirty_trigger_snapshot_artifacts() -> None:
    root = _make_workspace_temp_dir()
    try:
        notebook_path = root / "analysis.ipynb"
        outputs_root = root / "outputs"
        outputs_root.mkdir()
        watched_file = outputs_root / "result.csv"
        extra_watched_file = outputs_root / "figure.txt"

        _write_notebook(
            notebook_path,
            png_bytes=b"before-bytes",
            summary_text="before",
        )
        watched_file.write_text("value\n0\n", encoding="utf-8")
        extra_watched_file.write_text("before", encoding="utf-8")

        _init_git_repo(root)
        initial_commit = _git_head(root)

        _write_notebook(
            notebook_path,
            png_bytes=b"updated-png",
            summary_text="42",
            stream_text="stream output",
        )
        watched_file.write_text("value\n1\n", encoding="utf-8")
        extra_watched_file.write_text("after", encoding="utf-8")

        service = _make_snapshot_service()
        request = TriggerCellSnapshotRequest(
            notebook_context=NotebookContext(
                notebook_path=NotebookPath(str(notebook_path)),
                notebook_name="analysis.ipynb",
                cell_ids=(CellId("trigger-cell"), CellId("second-cell")),
                triggering_cell_id=CellId("trigger-cell"),
            ),
            commit_mode=CommitMode.NEVER,
            user_metadata=UserMetadata(run_label="baseline", tags=("baseline",)),
        )

        plan = service.plan_snapshot(
            request,
            notebook_metadata={"watched_paths": ["outputs"]},
        )
        record = service.execute_snapshot(plan, UserId("user-1"))

        assert record.source is SnapshotSource.TRIGGER_CELL
        assert record.trigger_cell_ids == (CellId("trigger-cell"),)
        assert record.executed_cell_ids == (
            CellId("trigger-cell"),
            CellId("second-cell"),
        )
        assert record.produced_value_summary == "42"
        assert record.commit_hash is None
        assert record.commit_url is None
        assert record.dirty_diff is not None
        assert "analysis.ipynb" in record.dirty_diff
        assert "outputs/result.csv" in record.dirty_diff
        assert record.repo.head_commit == initial_commit
        assert record.repo.is_dirty is True

        artifact_kinds = [artifact.kind for artifact in record.artifacts]
        assert artifact_kinds == [
            ArtifactKind.NOTEBOOK,
            ArtifactKind.FIGURE,
            ArtifactKind.FILE,
            ArtifactKind.FILE,
            ArtifactKind.DIFF,
        ]

        figure_artifact = next(
            artifact
            for artifact in record.artifacts
            if artifact.kind is ArtifactKind.FIGURE
        )
        assert figure_artifact.bytes_payload == b"updated-png"

        file_artifacts = [
            artifact
            for artifact in record.artifacts
            if artifact.kind is ArtifactKind.FILE
        ]
        assert [str(artifact.relative_path) for artifact in file_artifacts] == [
            "outputs/figure.txt",
            "outputs/result.csv",
        ]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_execute_snapshot_records_remaining_watch_diff_after_commit() -> None:
    root = _make_workspace_temp_dir()
    try:
        notebook_path = root / "analysis.ipynb"
        outputs_root = root / "outputs"
        outputs_root.mkdir()
        watched_file = outputs_root / "result.txt"

        _write_notebook(
            notebook_path,
            png_bytes=b"committed-before",
            summary_text="before",
        )
        watched_file.write_text("before", encoding="utf-8")

        _write_repo_config(root, stage_watched_paths_on_commit=False)
        _init_git_repo(root)
        initial_commit = _git_head(root)

        _write_notebook(
            notebook_path,
            png_bytes=b"committed-after",
            summary_text="after",
        )
        watched_file.write_text("after", encoding="utf-8")

        service = _make_snapshot_service()
        request = TriggerCellSnapshotRequest(
            notebook_context=NotebookContext(
                notebook_path=NotebookPath(str(notebook_path)),
                notebook_name="analysis.ipynb",
                cell_ids=(CellId("trigger-cell"),),
                triggering_cell_id=CellId("trigger-cell"),
            ),
            commit_mode=CommitMode.ALWAYS,
            user_metadata=UserMetadata(),
        )

        plan = service.plan_snapshot(
            request,
            notebook_metadata={"watched_paths": ["outputs"]},
        )
        record = service.execute_snapshot(plan, UserId("user-1"))

        assert record.commit_hash is not None
        assert record.commit_hash != initial_commit
        assert record.repo.head_commit == record.commit_hash
        assert record.repo.is_dirty is True
        assert _git_head(root) == record.commit_hash
        assert record.dirty_diff is not None
        assert "outputs/result.txt" in record.dirty_diff
        assert "analysis.ipynb" not in record.dirty_diff
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_execute_snapshot_omits_diff_after_committing_watched_paths() -> None:
    root = _make_workspace_temp_dir()
    try:
        notebook_path = root / "analysis.ipynb"
        outputs_root = root / "outputs"
        outputs_root.mkdir()
        watched_file = outputs_root / "result.txt"

        _write_notebook(
            notebook_path,
            png_bytes=b"committed-before",
            summary_text="before",
        )
        watched_file.write_text("before", encoding="utf-8")

        _write_repo_config(root, stage_watched_paths_on_commit=True)
        _init_git_repo(root)
        initial_commit = _git_head(root)

        _write_notebook(
            notebook_path,
            png_bytes=b"committed-after",
            summary_text="after",
        )
        watched_file.write_text("after", encoding="utf-8")

        service = _make_snapshot_service()
        request = TriggerCellSnapshotRequest(
            notebook_context=NotebookContext(
                notebook_path=NotebookPath(str(notebook_path)),
                notebook_name="analysis.ipynb",
                cell_ids=(CellId("trigger-cell"),),
                triggering_cell_id=CellId("trigger-cell"),
            ),
            commit_mode=CommitMode.ALWAYS,
            user_metadata=UserMetadata(),
        )

        plan = service.plan_snapshot(
            request,
            notebook_metadata={"watched_paths": ["outputs"]},
        )
        record = service.execute_snapshot(plan, UserId("user-1"))

        assert record.commit_hash is not None
        assert record.commit_hash != initial_commit
        assert record.repo.head_commit == record.commit_hash
        assert record.repo.is_dirty is False
        assert _git_head(root) == record.commit_hash
        assert record.dirty_diff is None
        assert not any(
            artifact.kind is ArtifactKind.DIFF for artifact in record.artifacts
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_execute_snapshot_handles_deleted_watch_file_and_truncates_summary() -> None:
    root = _make_workspace_temp_dir()
    try:
        notebook_path = root / "analysis.ipynb"
        missing_file = root / "outputs" / "deleted.txt"
        long_stream_text = "x" * 7000
        _write_notebook(
            notebook_path,
            stream_text=long_stream_text,
        )

        service = _make_snapshot_service()
        request = ManualSnapshotRequest(
            notebook_context=NotebookContext(
                notebook_path=NotebookPath(str(notebook_path)),
                notebook_name="analysis.ipynb",
            ),
            commit_mode=CommitMode.NEVER,
            user_metadata=UserMetadata(),
        )

        plan = service.plan_snapshot(
            request,
            notebook_metadata={"watched_paths": ["outputs/deleted.txt"]},
        )
        record = service.execute_snapshot(plan, UserId("user-1"))

        assert record.produced_value_summary is not None
        assert len(record.produced_value_summary) == 5000
        assert not any(
            artifact.kind is ArtifactKind.FILE for artifact in record.artifacts
        )
        assert missing_file.exists() is False
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _make_snapshot_service() -> SnapshotService:
    return SnapshotService(
        config_service=ConfigService(),
        git_service=DefaultGitService(),
        artifact_collector=DocumentArtifactCollector(),
        auth_service=AuthServiceImpl(),
        labarchives_adapter=LabArchivesAdapter(),
        run_fingerprint_service=RunFingerprintService(),
    )


def _write_notebook(
    notebook_path: Path,
    *,
    png_bytes: bytes | None = None,
    summary_text: str | None = None,
    stream_text: str | None = None,
) -> None:
    outputs: list[dict[str, object]] = []
    if png_bytes is not None or summary_text is not None:
        data: dict[str, object] = {}
        if png_bytes is not None:
            data["image/png"] = base64.b64encode(png_bytes).decode("utf-8")
        if summary_text is not None:
            data["text/plain"] = summary_text
        outputs.append({"data": data, "output_type": "display_data"})
    if stream_text is not None:
        outputs.append({"output_type": "stream", "text": stream_text})

    notebook_path.write_text(
        json.dumps(
            {
                "cells": [
                    {
                        "cell_type": "code",
                        "metadata": {},
                        "outputs": outputs,
                        "source": [],
                    }
                ],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        ),
        encoding="utf-8",
    )


def _write_repo_config(
    root: Path,
    *,
    stage_watched_paths_on_commit: bool,
) -> None:
    flag = "true" if stage_watched_paths_on_commit else "false"
    (root / ".save-my-jupyter.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "snapshot-tests"',
                "",
                "[git]",
                "stage_notebook_on_commit = true",
                f"stage_watched_paths_on_commit = {flag}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _init_git_repo(root: Path) -> None:
    _run(["git", "init"], root)
    _run(["git", "config", "user.email", "user@example.com"], root)
    _run(["git", "config", "user.name", "Save My Jupyter"], root)
    _run(["git", "add", "."], root)
    _run(["git", "commit", "-m", "initial"], root)


def _git_head(root: Path) -> str:
    return _run(["git", "rev-parse", "HEAD"], root).stdout.strip()


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _make_workspace_temp_dir() -> Path:
    root = Path.cwd() / f"tmp-snapshot-service-{uuid4().hex}"
    root.mkdir(parents=True)
    return root
