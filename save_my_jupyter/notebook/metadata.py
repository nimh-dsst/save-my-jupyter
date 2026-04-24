from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from save_my_jupyter.domain import NotebookPath

type JsonObject = dict[str, object]

_NOTEBOOK_METADATA_KEY = "save_my_jupyter"


def load_notebook_extension_metadata(
    notebook_path: NotebookPath,
) -> JsonObject:
    notebook_model = _load_json_mapping(Path(notebook_path).resolve())
    return extract_notebook_extension_metadata(notebook_model)


def extract_notebook_extension_metadata(
    notebook_model: Mapping[str, object] | None,
) -> JsonObject:
    if notebook_model is None:
        return {}

    metadata = _mapping_field(notebook_model, "metadata")
    if metadata is None:
        return {}

    extension_metadata = _mapping_field(metadata, _NOTEBOOK_METADATA_KEY)
    if extension_metadata is None:
        return {}

    return {str(key): value for key, value in extension_metadata.items()}


def _load_json_mapping(path: Path) -> Mapping[str, object] | None:
    try:
        raw_value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(raw_value, Mapping):
        return None
    return raw_value


def _mapping_field(
    mapping: Mapping[str, object],
    field_name: str,
) -> Mapping[str, object] | None:
    value = mapping.get(field_name)
    if not isinstance(value, Mapping):
        return None
    return {str(key): nested_value for key, nested_value in value.items()}
