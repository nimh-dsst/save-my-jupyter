"""Pure notebook-content extraction (target CAPTURE). The notebook JSON is
parsed at the boundary; these functions only transform it, so they need no
kernel and touch no filesystem. Figure naming, the execution summary, and MIME
resolution follow contracts C-CONTENT-03/04/07."""

from __future__ import annotations

import base64
import mimetypes
from collections.abc import Iterator, Mapping

from save_my_jupyter.domain.artifacts import FigureArtifact
from save_my_jupyter.domain.capture import NotebookOutline
from save_my_jupyter.domain.types import MimeType

NOTEBOOK_MIME_TYPE = MimeType("application/x-ipynb+json")
_EXECUTION_SUMMARY_MAX = 5000
_NO_SUMMARY = "(no execution summary available)"

# Fallback standalone figures use this priority when the notebook page is absent.
_FIGURE_MIME_EXTENSIONS: tuple[tuple[str, str], ...] = (
    ("image/png", "png"),
    ("image/jpeg", "jpg"),
    ("image/svg+xml", "svg"),
)
_BASE64_FIGURE_MIME_TYPES = frozenset({"image/png", "image/jpeg"})

# Watched-file MIME overrides (C-CONTENT-04); other extensions fall to guessing.
_SPECIAL_FILE_MIME_TYPES: Mapping[str, str] = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".tsv": "text/tab-separated-values",
    ".txt": "text/plain",
}


def outline_notebook(notebook: Mapping[str, object]) -> NotebookOutline:
    figure_count = len(extract_figures(notebook))
    has_output = any(_output_text(output) for output in _iter_outputs(notebook))
    return NotebookOutline(
        cell_count=len(notebook_cells(notebook)),
        figure_count=figure_count,
        has_execution_output=has_output,
    )


def notebook_metadata(notebook: Mapping[str, object]) -> Mapping[str, object]:
    metadata = _as_dict(notebook.get("metadata"))
    if metadata is None:
        return {}
    return _as_dict(metadata.get("save_my_jupyter")) or {}


def cell_sources(notebook: Mapping[str, object]) -> list[str]:
    return [source_text(cell.get("source")) for cell in notebook_cells(notebook)]


def triggering_cell_source(
    notebook: Mapping[str, object], triggering_cell_id: str | None
) -> str | None:
    if triggering_cell_id is None:
        return None
    for cell in notebook_cells(notebook):
        if cell.get("id") == triggering_cell_id:
            return source_text(cell.get("source"))
    return None


def source_text(source: object) -> str:
    if isinstance(source, str):
        return source
    if isinstance(source, list):
        return "".join(part for part in source if isinstance(part, str))
    return ""


def notebook_cells(notebook: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    cells = notebook.get("cells")
    if not isinstance(cells, list):
        return ()
    return tuple(
        normalized for cell in cells if (normalized := _as_dict(cell)) is not None
    )


def extract_figures(notebook: Mapping[str, object]) -> tuple[FigureArtifact, ...]:
    figures: list[FigureArtifact] = []
    for output in _iter_outputs(notebook):
        data = _as_dict(output.get("data"))
        if data is None:
            continue
        figure = _figure_from_output_data(data, index=len(figures) + 1)
        if figure is not None:
            figures.append(figure)
    return tuple(figures)


def summarize_execution(notebook: Mapping[str, object]) -> str:
    last_text: str | None = None
    for output in _iter_outputs(notebook):
        text = _output_text(output)
        if text:
            last_text = text
    if last_text is None:
        return _NO_SUMMARY
    return last_text[:_EXECUTION_SUMMARY_MAX]


def resolve_artifact_mime_type(filename: str) -> MimeType:
    suffix = _suffix(filename)
    if suffix in _SPECIAL_FILE_MIME_TYPES:
        return MimeType(_SPECIAL_FILE_MIME_TYPES[suffix])
    guessed, _encoding = mimetypes.guess_type(filename)
    return MimeType(guessed or "application/octet-stream")


def _figure_from_output_data(
    data: Mapping[str, object], *, index: int
) -> FigureArtifact | None:
    for mime_type, extension in _FIGURE_MIME_EXTENSIONS:
        payload = _join_text(data.get(mime_type))
        if payload is None:
            continue
        if mime_type in _BASE64_FIGURE_MIME_TYPES:
            content = base64.b64decode(payload)
        else:
            content = payload.encode("utf-8")
        return FigureArtifact(
            name=f"figure-{index:03d}.{extension}",
            mime_type=MimeType(mime_type),
            content=content,
        )
    return None


def _output_text(output: Mapping[str, object]) -> str | None:
    output_type = output.get("output_type")
    if output_type == "stream":
        return _join_text(output.get("text"))
    if output_type in ("execute_result", "display_data"):
        data = _as_dict(output.get("data"))
        return _join_text(data.get("text/plain")) if data is not None else None
    if output_type == "error":
        return _error_text(output)
    return None


def _error_text(output: Mapping[str, object]) -> str | None:
    lines: list[str] = []
    ename = output.get("ename")
    evalue = output.get("evalue")
    has_value = isinstance(evalue, str) and evalue
    if isinstance(ename, str) and ename:
        lines.append(f"{ename}: {evalue}" if has_value else ename)
    elif isinstance(evalue, str) and evalue:
        lines.append(evalue)
    traceback = _join_text(output.get("traceback"))
    if traceback:
        lines.append(traceback)
    return "\n".join(lines) if lines else None


def _iter_outputs(notebook: Mapping[str, object]) -> Iterator[Mapping[str, object]]:
    for cell in notebook_cells(notebook):
        outputs = cell.get("outputs")
        if not isinstance(outputs, list):
            continue
        for output in outputs:
            normalized = _as_dict(output)
            if normalized is not None:
                yield normalized


def _as_dict(value: object) -> dict[str, object] | None:
    """Normalize an untrusted JSON value into a string-keyed dict, or None."""
    if not isinstance(value, dict):
        return None
    return {str(key): nested for key, nested in value.items()}


def _join_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [part for part in value if isinstance(part, str)]
        if len(parts) != len(value):
            return None
        return "".join(parts)
    return None


def _suffix(filename: str) -> str:
    dot = filename.rfind(".")
    if dot <= 0:
        return ""
    return filename[dot:].lower()
