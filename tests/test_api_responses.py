from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from save_my_jupyter.api.responses import (
    build_state_payload,
    serialize_submission_result,
)
from save_my_jupyter.domain import (
    CellId,
    CommitHash,
    CommitMode,
    EffectiveConfig,
    LabArchivesNotebookName,
    LabArchivesRootPath,
    LabArchivesTarget,
    NotebookMetadataConfig,
    RelativeRepoPath,
    RelativeWatchPath,
    RemoteUrl,
    RepoRootPath,
    ResolvedRepoContext,
    SnapshotAccepted,
    SnapshotId,
    TriggerMode,
)
from save_my_jupyter.services.auth import AuthStatusResult


def test_build_state_payload_serializes_effective_state() -> None:
    root = _make_workspace_temp_dir()
    try:
        repo_root = root / "repo"
        repo_root.mkdir()
        repo_config_path = repo_root / ".save-my-jupyter.toml"

        payload = build_state_payload(
            auth_status=AuthStatusResult(
                status="authenticated",
                user_email="user@example.com",
                stored_user_email="stored@example.com",
                stored_notebook_names=("Snapshots",),
            ),
            effective_config=EffectiveConfig(
                all_cells_trigger=False,
                commit_mode=CommitMode.ALWAYS,
                watched_paths=(RelativeWatchPath("outputs"),),
                include_notebook_file=True,
                include_diff_when_dirty=False,
                target=LabArchivesTarget(
                    notebook_name=LabArchivesNotebookName("Snapshots"),
                    root_path=LabArchivesRootPath("Notebook Log"),
                ),
                metadata_template={"source": "manual"},
                stage_notebook_on_commit=True,
                stage_watched_paths_on_commit=False,
                commit_message_template="snapshot",
            ),
            notebook_metadata=NotebookMetadataConfig(
                enabled=True,
                trigger_mode=TriggerMode.ALL_CELLS,
                trigger_cell_ids=frozenset({CellId("cell-1")}),
                watched_paths=(RelativeWatchPath("outputs"),),
                labarchives_target_notebook=LabArchivesNotebookName("Snapshots"),
                labarchives_target_root_path=LabArchivesRootPath("Notebook Log"),
                default_metadata={"tag": "alpha"},
            ),
            repo=ResolvedRepoContext(
                repo_root=RepoRootPath(str(repo_root)),
                relative_notebook_path=RelativeRepoPath("notebooks/analysis.ipynb"),
                remote_url=RemoteUrl("https://example.com/repo.git"),
                head_commit=CommitHash("abc123"),
                is_dirty=True,
            ),
            repo_config_loaded=True,
            repo_config_path=repo_config_path,
        )

        assert payload == {
            "auth": {
                "pendingRequestId": None,
                "storedNotebookNames": ["Snapshots"],
                "storedUserEmail": "stored@example.com",
                "status": "authenticated",
                "userEmail": "user@example.com",
            },
            "effectiveConfig": {
                "allCellsTrigger": False,
                "commitMessageTemplate": "snapshot",
                "commitMode": "always",
                "includeDiffWhenDirty": False,
                "includeNotebookFile": True,
                "metadataTemplate": {"source": "manual"},
                "stageNotebookOnCommit": True,
                "stageWatchedPathsOnCommit": False,
                "target": {
                    "notebookName": "Snapshots",
                    "rootPath": "Notebook Log",
                },
                "watchedPaths": ["outputs"],
            },
            "notebookMetadata": {
                "all_cells_trigger": True,
                "default_metadata": {"tag": "alpha"},
                "enabled": True,
                "labarchives_target_notebook": "Snapshots",
                "labarchives_target_root_path": "Notebook Log",
                "trigger_cell_ids": ["cell-1"],
                "watched_paths": ["outputs"],
            },
            "repo": {
                "headCommit": "abc123",
                "isDirty": True,
                "relativeNotebookPath": "notebooks/analysis.ipynb",
                "remoteUrl": "https://example.com/repo.git",
                "repoRoot": str(repo_root),
            },
            "repoConfigLoaded": True,
            "repoConfigPath": str(repo_config_path),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_serialize_submission_result_includes_post_save_references() -> None:
    payload = serialize_submission_result(
        SnapshotAccepted(
            job_id="job-1",
            queue_position=0,
            snapshot_id=SnapshotId("snapshot-1"),
            commit_hash=CommitHash("abcdef1234567890"),
            commit_url="https://git.example.test/commit/abcdef1234567890",
            commit_created=True,
            labarchives_page_id="page-1",
            labarchives_page_name="00 Metadata",
            labarchives_directory_name="2026-04-10T15-00-00.000_snapshot-1",
            labarchives_meta_page_id="page-1",
            labarchives_meta_page_name="00 Metadata",
            labarchives_page_count=3,
        )
    )

    assert payload == {
        "commitCreated": True,
        "commitHash": "abcdef1234567890",
        "commitUrl": "https://git.example.test/commit/abcdef1234567890",
        "jobId": "job-1",
        "labarchivesDirectoryName": "2026-04-10T15-00-00.000_snapshot-1",
        "labarchivesMetaPageId": "page-1",
        "labarchivesMetaPageName": "00 Metadata",
        "labarchivesPageCount": 3,
        "labarchivesPageId": "page-1",
        "labarchivesPageName": "00 Metadata",
        "queuePosition": 0,
        "snapshotId": "snapshot-1",
        "status": "accepted",
    }


def _make_workspace_temp_dir() -> Path:
    root = Path.cwd() / f"tmp-api-responses-{uuid4().hex}"
    root.mkdir(parents=True)
    return root
