from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from save_my_jupyter.adapters.labarchives import LabArchivesAdapter
from save_my_jupyter.config.service import ConfigService
from save_my_jupyter.domain import (
    ArtifactKind,
    CellId,
    CommitMode,
    DiffArtifact,
    ManualSnapshotRequest,
    NotebookContext,
    NotebookPath,
    SnapshotSource,
    TriggerCellSnapshotRequest,
    UserId,
    UserMetadata,
)
from save_my_jupyter.errors import CommitCreationError
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
        assert record.produced_value_summary is not None
        assert "Result Summary" in record.produced_value_summary
        assert "Cell        : Cell 1" in record.produced_value_summary
        assert "Output      : 1" in record.produced_value_summary
        assert "Output type : display_data" in record.produced_value_summary
        assert 'Source      : data["text/plain"]' in record.produced_value_summary
        assert "42" in record.produced_value_summary
        assert "stream output" in record.produced_value_summary
        assert record.commit_hash is None
        assert record.commit_created is False
        assert record.commit_url is None
        assert record.dirty_diff is not None
        assert "analysis.ipynb" in record.dirty_diff
        assert "outputs/result.csv" in record.dirty_diff
        assert record.diff_base_commit == initial_commit
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
        assert figure_artifact.display_name == "figure-cell-1-output-01.png"

        diff_artifact = next(
            artifact
            for artifact in record.artifacts
            if artifact.kind is ArtifactKind.DIFF
        )
        assert isinstance(diff_artifact, DiffArtifact)
        assert "analysis.ipynb" not in diff_artifact.diff_text
        assert "outputs/result.csv" in diff_artifact.diff_text
        assert "outputs/figure.txt" in diff_artifact.diff_text

        file_artifacts = [
            artifact
            for artifact in record.artifacts
            if artifact.kind is ArtifactKind.FILE
        ]
        assert [str(artifact.relative_path) for artifact in file_artifacts] == [
            "outputs/figure.txt",
            "outputs/result.csv",
        ]
        assert [artifact.bytes_payload for artifact in file_artifacts] == [
            b"after",
            watched_file.read_bytes(),
        ]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_execute_snapshot_preserves_pre_commit_diff_after_partial_commit() -> None:
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
        assert record.commit_created is True
        assert record.repo.head_commit == record.commit_hash
        assert record.repo.is_dirty is True
        assert _git_head(root) == record.commit_hash
        assert record.dirty_diff is not None
        assert "outputs/result.txt" in record.dirty_diff
        assert "analysis.ipynb" in record.dirty_diff
        assert record.diff_base_commit == initial_commit
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_execute_snapshot_preserves_pre_commit_diff_after_full_commit() -> None:
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
        assert record.commit_created is True
        assert record.repo.head_commit == record.commit_hash
        assert record.repo.is_dirty is False
        assert _git_head(root) == record.commit_hash
        assert record.dirty_diff is not None
        assert "analysis.ipynb" in record.dirty_diff
        assert "outputs/result.txt" in record.dirty_diff
        assert record.diff_base_commit == initial_commit
        assert any(artifact.kind is ArtifactKind.DIFF for artifact in record.artifacts)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_execute_snapshot_reuses_head_when_only_unrelated_paths_are_staged() -> None:
    root = _make_workspace_temp_dir()
    try:
        notebook_path = root / "analysis.ipynb"
        outputs_root = root / "outputs"
        outputs_root.mkdir()
        watched_file = outputs_root / "result.txt"
        unrelated_path = root / "README.txt"

        _write_notebook(
            notebook_path,
            png_bytes=b"before",
            summary_text="before",
        )
        watched_file.write_text("before", encoding="utf-8")
        unrelated_path.write_text("base", encoding="utf-8")

        _write_repo_config(root, stage_watched_paths_on_commit=True)
        _init_git_repo(root)
        initial_commit = _git_head(root)

        unrelated_path.write_text("changed", encoding="utf-8")
        _run(["git", "add", "README.txt"], root)

        service = _make_snapshot_service()
        request = ManualSnapshotRequest(
            notebook_context=NotebookContext(
                notebook_path=NotebookPath(str(notebook_path)),
                notebook_name="analysis.ipynb",
            ),
            commit_mode=CommitMode.ALWAYS,
            user_metadata=UserMetadata(),
        )

        plan = service.plan_snapshot(
            request,
            notebook_metadata={"watched_paths": ["outputs"]},
        )
        record = service.execute_snapshot(plan, UserId("user-1"))

        assert record.commit_hash == initial_commit
        assert record.commit_created is False
        assert record.repo.head_commit == initial_commit
        assert _git_head(root) == initial_commit
        assert _run(
            ["git", "diff", "--cached", "--name-only"], root
        ).stdout.splitlines() == ["README.txt"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_execute_snapshot_commit_adds_changed_notebook_and_watched_paths() -> None:
    root = _make_workspace_temp_dir()
    try:
        notebook_path = root / "analysis.ipynb"
        outputs_root = root / "outputs"
        outputs_root.mkdir()
        watched_file = outputs_root / "result.txt"

        _write_notebook(
            notebook_path,
            png_bytes=b"before",
            summary_text="before",
        )
        watched_file.write_text("before", encoding="utf-8")

        _write_repo_config(root, stage_watched_paths_on_commit=True)
        _init_git_repo(root)
        initial_commit = _git_head(root)

        _write_notebook(
            notebook_path,
            png_bytes=b"after",
            summary_text="after",
        )
        watched_file.write_text("after", encoding="utf-8")

        service = _make_snapshot_service()
        request = ManualSnapshotRequest(
            notebook_context=NotebookContext(
                notebook_path=NotebookPath(str(notebook_path)),
                notebook_name="analysis.ipynb",
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
        assert record.commit_created is True
        assert record.repo.head_commit == record.commit_hash
        assert _git_head(root) == record.commit_hash
        assert set(
            _run(
                ["git", "show", "--pretty=", "--name-only", "HEAD"], root
            ).stdout.splitlines()
        ) == {"analysis.ipynb", "outputs/result.txt"}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_execute_snapshot_commit_includes_changed_repo_config_only() -> None:
    root = _make_workspace_temp_dir()
    try:
        notebook_path = root / "analysis.ipynb"

        _write_notebook(
            notebook_path,
            summary_text="before",
        )
        _write_repo_config(root, stage_watched_paths_on_commit=False)
        _init_git_repo(root)
        initial_commit = _git_head(root)

        _write_repo_config(
            root,
            stage_watched_paths_on_commit=False,
            commit_message_template="snapshot: {notebook_name} config-update",
        )

        service = _make_snapshot_service()
        request = ManualSnapshotRequest(
            notebook_context=NotebookContext(
                notebook_path=NotebookPath(str(notebook_path)),
                notebook_name="analysis.ipynb",
            ),
            commit_mode=CommitMode.ALWAYS,
            user_metadata=UserMetadata(),
        )

        plan = service.plan_snapshot(request)
        record = service.execute_snapshot(plan, UserId("user-1"))

        assert record.commit_hash is not None
        assert record.commit_hash != initial_commit
        assert record.commit_created is True
        assert record.repo.head_commit == record.commit_hash
        assert record.repo.is_dirty is False
        assert record.dirty_diff is None
        assert _git_head(root) == record.commit_hash
        assert _run(
            ["git", "show", "--pretty=", "--name-only", "HEAD"], root
        ).stdout.splitlines() == [".save-my-jupyter.toml"]
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


def test_execute_snapshot_ignores_ipynb_checkpoints() -> None:
    root = _make_workspace_temp_dir()
    try:
        notebook_path = root / "analysis.ipynb"
        outputs_root = root / "outputs"
        checkpoint_root = outputs_root / ".ipynb_checkpoints"
        checkpoint_root.mkdir(parents=True)

        _write_notebook(
            notebook_path,
            summary_text="before",
        )

        _init_git_repo(root)

        checkpoint_file = checkpoint_root / "result-checkpoint.csv"
        checkpoint_file.write_text("value\n1\n", encoding="utf-8")

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
            notebook_metadata={"watched_paths": ["outputs"]},
        )
        record = service.execute_snapshot(plan, UserId("user-1"))

        assert record.repo.is_dirty is False
        assert record.dirty_diff is None
        assert not any(
            artifact.kind is ArtifactKind.FILE for artifact in record.artifacts
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_execute_snapshot_uses_default_python_watch_scope_for_changed_files() -> None:
    root = _make_workspace_temp_dir()
    try:
        notebook_path = root / "analysis.ipynb"
        package_root = root / "package"
        package_root.mkdir()
        changed_file = package_root / "changed.py"
        unchanged_file = package_root / "unchanged.py"

        _write_notebook(
            notebook_path,
            summary_text="before",
        )
        changed_file.write_text("value = 1\n", encoding="utf-8")
        unchanged_file.write_text("value = 2\n", encoding="utf-8")

        _init_git_repo(root)

        _write_notebook(
            notebook_path,
            summary_text="after",
        )
        changed_file.write_text("value = 3\n", encoding="utf-8")

        service = _make_snapshot_service()
        request = ManualSnapshotRequest(
            notebook_context=NotebookContext(
                notebook_path=NotebookPath(str(notebook_path)),
                notebook_name="analysis.ipynb",
            ),
            commit_mode=CommitMode.NEVER,
            user_metadata=UserMetadata(),
        )

        plan = service.plan_snapshot(request)
        assert tuple(map(str, plan.effective_config.watched_paths)) == ("**/*.py",)

        record = service.execute_snapshot(plan, UserId("user-1"))

        file_artifacts = [
            artifact
            for artifact in record.artifacts
            if artifact.kind is ArtifactKind.FILE
        ]
        assert [str(artifact.relative_path) for artifact in file_artifacts] == [
            "package/changed.py"
        ]
        assert record.dirty_diff is not None
        assert "package/changed.py" in record.dirty_diff
        assert "package/unchanged.py" not in record.dirty_diff
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_execute_snapshot_preserves_changed_python_artifacts_after_commit() -> None:
    root = _make_workspace_temp_dir()
    try:
        notebook_path = root / "analysis.ipynb"
        changed_file = root / "changed.py"

        _write_notebook(
            notebook_path,
            summary_text="before",
        )
        changed_file.write_text("value = 1\n", encoding="utf-8")

        _write_repo_config(root, stage_watched_paths_on_commit=True)
        _init_git_repo(root)

        _write_notebook(
            notebook_path,
            summary_text="after",
        )
        changed_file.write_text("value = 2\n", encoding="utf-8")

        service = _make_snapshot_service()
        request = ManualSnapshotRequest(
            notebook_context=NotebookContext(
                notebook_path=NotebookPath(str(notebook_path)),
                notebook_name="analysis.ipynb",
            ),
            commit_mode=CommitMode.ALWAYS,
            user_metadata=UserMetadata(),
        )

        plan = service.plan_snapshot(request)
        record = service.execute_snapshot(plan, UserId("user-1"))

        assert record.commit_hash is not None
        assert record.commit_created is True
        assert record.repo.is_dirty is False
        assert record.dirty_diff is not None
        assert "analysis.ipynb" in record.dirty_diff
        assert "changed.py" in record.dirty_diff

        file_artifacts = [
            artifact
            for artifact in record.artifacts
            if artifact.kind is ArtifactKind.FILE
        ]
        assert [str(artifact.relative_path) for artifact in file_artifacts] == [
            "changed.py"
        ]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_execute_snapshot_rejects_unresolved_prompt_commit_mode() -> None:
    root = _make_workspace_temp_dir()
    try:
        notebook_path = root / "analysis.ipynb"
        _write_notebook(notebook_path, summary_text="result")
        _init_git_repo(root)
        notebook_path.write_text('{"cells":[]}', encoding="utf-8")

        service = _make_snapshot_service()
        request = ManualSnapshotRequest(
            notebook_context=NotebookContext(
                notebook_path=NotebookPath(str(notebook_path)),
                notebook_name="analysis.ipynb",
            ),
            commit_mode=CommitMode.PROMPT,
            user_metadata=UserMetadata(),
        )

        plan = service.plan_snapshot(request)

        with pytest.raises(CommitCreationError) as exc_info:
            service.execute_snapshot(plan, UserId("user-1"))

        assert exc_info.value.code == "unresolved_commit_mode"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_execute_snapshot_summarizes_image_only_and_error_outputs() -> None:
    root = _make_workspace_temp_dir()
    try:
        notebook_path = root / "analysis.ipynb"
        _write_notebook(
            notebook_path,
            error_output={
                "ename": "ValueError",
                "evalue": "bad value",
                "traceback": ["Traceback line\n"],
            },
            image_only_bytes=b"image-only",
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

        plan = service.plan_snapshot(request)
        record = service.execute_snapshot(plan, UserId("user-1"))

        assert record.produced_value_summary is not None
        assert "Image output: image/png" in record.produced_value_summary
        assert "ValueError: bad value" in record.produced_value_summary
        assert "Traceback line" in record.produced_value_summary
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
    error_output: dict[str, object] | None = None,
    image_only_bytes: bytes | None = None,
    png_bytes: bytes | None = None,
    summary_text: str | None = None,
    stream_text: str | None = None,
) -> None:
    outputs: list[dict[str, object]] = []
    if image_only_bytes is not None:
        outputs.append(
            {
                "data": {
                    "image/png": base64.b64encode(image_only_bytes).decode("utf-8"),
                },
                "output_type": "display_data",
            }
        )
    if png_bytes is not None or summary_text is not None:
        data: dict[str, object] = {}
        if png_bytes is not None:
            data["image/png"] = base64.b64encode(png_bytes).decode("utf-8")
        if summary_text is not None:
            data["text/plain"] = summary_text
        outputs.append({"data": data, "output_type": "display_data"})
    if stream_text is not None:
        outputs.append({"output_type": "stream", "text": stream_text})
    if error_output is not None:
        outputs.append({"output_type": "error", **error_output})

    notebook_path.write_text(
        json.dumps(
            {
                "cells": [
                    {
                        "cell_type": "code",
                        "id": "cell-1",
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
    commit_message_template: str = "snapshot: {notebook_name} {timestamp}",
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
                f'commit_message_template = "{commit_message_template}"',
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
