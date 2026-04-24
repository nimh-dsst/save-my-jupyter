from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

from save_my_jupyter.api.responses import (
    build_state_payload,
    load_notebook_extension_metadata,
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
    NotebookPath,
    RelativeRepoPath,
    RelativeWatchPath,
    RemoteUrl,
    RepoRootPath,
    ResolvedPathRule,
    ResolvedRepoContext,
    TriggerMode,
)
from save_my_jupyter.services.auth import AuthStatusResult


def test_load_notebook_extension_metadata_reads_extension_block(
) -> None:
    root = _make_workspace_temp_dir()
    try:
        notebook_path = root / "analysis.ipynb"
        notebook_path.write_text(
            json.dumps(
                {
                    "metadata": {
                        "save_my_jupyter": {
                            "enabled": False,
                            "watched_paths": ["outputs"],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        metadata = load_notebook_extension_metadata(NotebookPath(str(notebook_path)))

        assert metadata == {
            "enabled": False,
            "watched_paths": ["outputs"],
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_load_notebook_extension_metadata_returns_empty_for_non_mapping_root(
) -> None:
    root = _make_workspace_temp_dir()
    try:
        notebook_path = root / "analysis.ipynb"
        notebook_path.write_text("[]", encoding="utf-8")

        metadata = load_notebook_extension_metadata(NotebookPath(str(notebook_path)))

        assert metadata == {}
    finally:
        shutil.rmtree(root, ignore_errors=True)


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
            path_rule=ResolvedPathRule(
                rule_name="analysis",
                match_paths=(RelativeRepoPath("notebooks"),),
                watch_paths=(RelativeWatchPath("outputs"),),
                include_paths=(RelativeWatchPath("figures"),),
                exclude_paths=(RelativeWatchPath("tmp"),),
                target=LabArchivesTarget(
                    notebook_name=LabArchivesNotebookName("Snapshots"),
                    root_path=LabArchivesRootPath("Notebook Log"),
                ),
                metadata_template={"rule": "matched"},
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
            "pathRule": {
                "includePaths": ["figures"],
                "metadataTemplate": {"rule": "matched"},
                "name": "analysis",
                "target": {
                    "notebookName": "Snapshots",
                    "rootPath": "Notebook Log",
                },
                "watchPaths": ["outputs"],
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


def _make_workspace_temp_dir() -> Path:
    root = Path.cwd() / f"tmp-api-responses-{uuid4().hex}"
    root.mkdir(parents=True)
    return root
