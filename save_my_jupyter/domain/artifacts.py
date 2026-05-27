from __future__ import annotations

from dataclasses import dataclass

from save_my_jupyter.domain.types import MimeType


@dataclass(frozen=True, slots=True, kw_only=True)
class FigureArtifact:
    """One image extracted from a cell output (contract C-CONTENT-03). ``name``
    is the contract-shaped ``figure-NNN.<ext>``; ``content`` is decoded bytes."""

    name: str
    mime_type: MimeType
    content: bytes
