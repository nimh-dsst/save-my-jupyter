from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

from save_my_jupyter.domain import NotebookPath
from save_my_jupyter.notebook import (
    extract_notebook_extension_metadata,
    load_notebook_extension_metadata,
)


def test_extract_notebook_extension_metadata_reads_extension_block() -> None:
    metadata = extract_notebook_extension_metadata(
        {
            "metadata": {
                "save_my_jupyter": {
                    "enabled": False,
                    "watched_paths": ["outputs"],
                }
            }
        }
    )

    assert metadata == {
        "enabled": False,
        "watched_paths": ["outputs"],
    }


def test_extract_notebook_extension_metadata_returns_empty_for_non_mapping_root() -> (
    None
):
    metadata = extract_notebook_extension_metadata(None)

    assert metadata == {}


def test_load_notebook_extension_metadata_reads_file() -> None:
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


def test_load_notebook_extension_metadata_returns_empty_for_non_mapping_root() -> None:
    root = _make_workspace_temp_dir()
    try:
        notebook_path = root / "analysis.ipynb"
        notebook_path.write_text("[]", encoding="utf-8")

        metadata = load_notebook_extension_metadata(NotebookPath(str(notebook_path)))

        assert metadata == {}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _make_workspace_temp_dir() -> Path:
    root = Path.cwd() / f"tmp-notebook-metadata-{uuid4().hex}"
    root.mkdir(parents=True)
    return root
