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


@dataclass(frozen=True, slots=True, kw_only=True)
class NotebookPayload:
    """The notebook file as it will be uploaded (contract C-CONTENT-01)."""

    filename: str
    content: bytes


@dataclass(frozen=True, slots=True, kw_only=True)
class WatchedFileArtifact:
    """A watched file read at snapshot time, ready to upload (C-CONTENT-04)."""

    filename: str
    mime_type: MimeType
    content: bytes
    relative_path: str | None = None
