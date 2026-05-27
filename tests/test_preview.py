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
from save_my_jupyter.domain.types import NotebookPath


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


def _request() -> SnapshotRequest:
    return SnapshotRequest(
        source=SnapshotSource.MANUAL,
        notebook_context=NotebookContext(
            notebook_path=NotebookPath("analysis/nb.ipynb"), notebook_name="nb.ipynb"
        ),
        metadata=RequestedMetadata(),
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


def test_preview_plans_notebook_and_figure_and_marks_frontend_source() -> None:
    result = build_preview(
        _request(),
        git_inspector=_NoRepoInspector(),
        filesystem=_EmptyFileSystem(),
        user_settings=UserSettingsConfig(),
    )
    kinds = {artifact.kind for artifact in result.plan.artifacts}
    assert ArtifactKind.NOTEBOOK in kinds
    assert ArtifactKind.FIGURE in kinds
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
