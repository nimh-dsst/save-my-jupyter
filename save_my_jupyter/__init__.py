from __future__ import annotations

__all__ = [
    "_jupyter_labextension_paths",
    "_jupyter_server_extension_points",
    "_load_jupyter_server_extension",
]
__version__ = "0.1.0"


def _jupyter_labextension_paths() -> list[dict[str, str]]:
    return [{"src": "labextension", "dest": "@save-my-jupyter/extension"}]


def _jupyter_server_extension_points() -> list[dict[str, str]]:
    return [{"module": "save_my_jupyter"}]


def _load_jupyter_server_extension(server_app: object) -> None:
    from .extension import SaveMyJupyterApp

    SaveMyJupyterApp.load_classic_server_extension(server_app)  # type: ignore[no-untyped-call]
