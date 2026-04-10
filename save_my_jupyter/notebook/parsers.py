from __future__ import annotations

from collections.abc import Mapping

from save_my_jupyter.config.parsers import parse_notebook_metadata
from save_my_jupyter.domain import NotebookMetadataConfig


def parse_notebook_metadata_mapping(
    raw: Mapping[str, object],
) -> NotebookMetadataConfig:
    return parse_notebook_metadata(raw)
