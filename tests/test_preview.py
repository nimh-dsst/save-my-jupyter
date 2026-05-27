from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from save_my_jupyter.application.preview import build_preview
from save_my_jupyter.domain.config import UserSettingsConfig
from save_my_jupyter.domain.enums import ArtifactKind, SnapshotSource
from save_my_jupyter.domain.provenance import ConfigLayer
from save_my_jupyter.domain.repo import RepoContext
from save_my_jupyter.domain.requests import (
    NotebookContext,
    RequestedMetadata,
    SnapshotRequest,
)
from save_my_jupyter.domain.types import NotebookPath, RelativeWatchPath


class _NoRepoInspector:
    def resolve_repo(self, notebook_path: NotebookPath) -> RepoContext:
        del notebook_path
        return RepoContext(
            repo_root=None,
            relative_notebook_path=None,
            remote_url=None,
            head_commit=None,
            is_dirty=False,
        )


class _EmptyFileSystem:
    def exists(self, path: Path) -> bool:
        del path
        return False

    def is_file(self, path: Path) -> bool:
        del path
        return False

    def read_bytes(self, path: Path) -> bytes:
        del path
        return b""

    def iter_files(self, root: Path, pattern: str) -> Iterator[Path]:
        del root, pattern
        return iter(())


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
        del root, pattern
        return iter(())


def _request(
    *, watched_paths: tuple[RelativeWatchPath, ...] | None = None
) -> SnapshotRequest:
    return SnapshotRequest(
        source=SnapshotSource.MANUAL,
        notebook_context=NotebookContext(
            notebook_path=NotebookPath("analysis/nb.ipynb"), notebook_name="nb.ipynb"
        ),
        metadata=RequestedMetadata(),
        watched_paths=watched_paths,
        notebook_content={
            "cells": [
                {
                    "source": "# smj: tags=baseline",
                    "outputs": [
                        {"output_type": "display_data", "data": {"image/png": "QQ=="}}
                    ],
                }
            ],
            "metadata": {},
        },
    )


def test_preview_plans_notebook_with_inline_figures_and_marks_frontend_source() -> None:
    result = build_preview(
        _request(),
        git_inspector=_NoRepoInspector(),
        filesystem=_EmptyFileSystem(),
        user_settings=UserSettingsConfig(),
    )
    kinds = {artifact.kind for artifact in result.plan.artifacts}
    assert ArtifactKind.NOTEBOOK in kinds
    assert ArtifactKind.FIGURE not in kinds
    assert result.source == "frontend"
    assert "baseline" in result.plan.tags


def test_preview_destination_is_inferred_on_a_fresh_repo() -> None:
    result = build_preview(
        _request(),
        git_inspector=_NoRepoInspector(),
        filesystem=_EmptyFileSystem(),
        user_settings=UserSettingsConfig(),
    )
    assert result.provenance["target_notebook"] is ConfigLayer.INFERRED
    assert result.provenance["target_root_path"] is ConfigLayer.INFERRED
    assert result.repo.repo_root is None
    assert result.repo_config_path is not None
    assert result.repo_config_path.endswith(".save-my-jupyter.toml")
    assert result.repo_config_loaded is False
    assert result.effective.target.notebook_name == "Jupyter Snapshots"


def test_preview_uses_request_watched_paths() -> None:
    result = build_preview(
        _request(watched_paths=(RelativeWatchPath("outputs"),)),
        git_inspector=_NoRepoInspector(),
        filesystem=_EmptyFileSystem(),
        user_settings=UserSettingsConfig(),
    )
    assert result.provenance["watched_paths"] is ConfigLayer.REQUEST
    assert any(artifact.summary == "outputs" for artifact in result.plan.artifacts)


def test_preview_carries_user_metadata_summary() -> None:
    result = build_preview(
        SnapshotRequest(
            source=SnapshotSource.MANUAL,
            notebook_context=NotebookContext(
                notebook_path=NotebookPath("analysis/nb.ipynb"),
                notebook_name="nb.ipynb",
            ),
            metadata=RequestedMetadata(
                run_label="run-1",
                notes="operator note",
                extra_fields={"operator": "Ada"},
            ),
            notebook_content={"cells": [], "metadata": {}},
        ),
        git_inspector=_NoRepoInspector(),
        filesystem=_EmptyFileSystem(),
        user_settings=UserSettingsConfig(),
    )

    assert result.plan.run_label == "run-1"
    assert result.notes == "operator note"
    assert result.extra_fields == {"operator": "Ada"}


def test_preview_loads_non_git_project_config_from_project_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    notebook_path = root / "analysis" / "nb.ipynb"
    result = build_preview(
        SnapshotRequest(
            source=SnapshotSource.MANUAL,
            notebook_context=NotebookContext(
                notebook_path=NotebookPath(str(notebook_path)),
                notebook_name="nb.ipynb",
            ),
            metadata=RequestedMetadata(),
            notebook_content={"cells": [], "metadata": {}},
        ),
        git_inspector=_NoRepoInspector(),
        filesystem=_MemoryFileSystem(
            {
                root / "pyproject.toml": b"[project]\nname = 'demo'\n",
                root
                / ".save-my-jupyter.toml": b"[defaults]\nwatch_paths = ['outputs']\n",
            }
        ),
        user_settings=UserSettingsConfig(),
    )

    assert result.repo_config_loaded is True
    assert result.repo_config_path == str(root / ".save-my-jupyter.toml")
    assert result.effective.watched_paths == (RelativeWatchPath("outputs"),)
