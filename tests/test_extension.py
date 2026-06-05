from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

from save_my_jupyter.extension import SaveMyJupyterApp


def test_snapshots_directory_is_hidden_under_server_root(tmp_path: Path) -> None:
    app = SaveMyJupyterApp()
    app.serverapp = cast("object", SimpleNamespace(root_dir=str(tmp_path)))

    assert app._snapshots_dir() == tmp_path / ".save-my-jupyter-snapshots"
