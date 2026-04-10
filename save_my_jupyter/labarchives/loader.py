from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from types import ModuleType

from save_my_jupyter.errors import LabArchivesWriteError

_LABAPI_CANDIDATES = (
    Path.home() / "projects" / "labarchives-api" / "src",
    Path.home() / "Downloads" / "labarchives-api" / "src",
)


def load_labapi() -> ModuleType:
    try:
        return import_module("labapi")
    except ImportError:
        for candidate in _LABAPI_CANDIDATES:
            if not candidate.exists():
                continue
            sys.path.insert(0, str(candidate))
            try:
                return import_module("labapi")
            except ImportError:
                continue

    raise LabArchivesWriteError(
        "labapi is not installed and could not be loaded from a local checkout.",
        code="missing_labapi",
        context={"candidates": ", ".join(str(path) for path in _LABAPI_CANDIDATES)},
    )
