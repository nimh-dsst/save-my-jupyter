"""Readable notebook artifact rendering (target CONTENT, contract C-DEST-03).

The raw ``.ipynb`` remains the source of truth and is still attached. This
renderer gives the LabArchives page itself a stable, readable HTML view of the
cells and captured outputs without relying on a live notebook kernel.
"""

from __future__ import annotations

import base64
import builtins
import io
import json
import keyword
import tokenize
from collections.abc import Mapping, Sequence
from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from save_my_jupyter.domain.delivery import NotebookDiff

_PAGE_STYLE = (
    "font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;color:#24292f;"
)
_CELL_STYLE = (
    "border:1px solid #d0d7de;border-radius:6px;margin:12px 0;"
    "padding:12px;background:#fff;"
)
_HEADING_STYLE = "margin:0 0 10px 0;font-size:16px;"
_SUBHEADING_STYLE = "margin:12px 0 6px 0;font-size:13px;"
_SOURCE_STYLE = (
    "white-space:pre-wrap;margin:0;padding:10px;background:#f6f8fa;"
    "border:1px solid #d8dee4;border-radius:4px;"
)
_MARKDOWN_STYLE = (
    "white-space:pre-wrap;margin:0;padding:10px;background:#fff;"
    "border:1px solid #d8dee4;border-radius:4px;"
)
_OUTPUT_STYLE = (
    "border:1px solid #d8dee4;border-radius:4px;margin:8px 0;padding:8px;"
    "background:#fbfbfb;"
)
_OUTPUT_LABEL_STYLE = "font-weight:600;margin-bottom:6px;"
_IMAGE_STYLE = "display:block;max-width:100%;height:auto;margin:8px 0;"
_IMAGE_MIME_TYPES = (
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/gif",
    "image/webp",
    "image/svg+xml",
)
_PYTHON_NAMES = set(dir(builtins))
_TOKEN_STYLES = {
    "builtin": "color:#6639ba;",
    "comment": "color:#6e7781;font-style:italic;",
    "keyword": "color:#cf222e;font-weight:600;",
    "number": "color:#0550ae;",
    "operator": "color:#cf222e;",
    "string": "color:#0a3069;",
}


def render_notebook_artifact_html(
    filename: str,
    content: bytes,
    *,
    notebook_diff: NotebookDiff | None = None,
) -> str | None:
    """Return readable HTML for a notebook artifact, or ``None`` if invalid."""
    try:
        parsed = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, Mapping):
        return None
    return render_notebook_html(filename, parsed, notebook_diff=notebook_diff)


def render_notebook_html(
    filename: str,
    notebook: Mapping[str, object],
    *,
    notebook_diff: NotebookDiff | None = None,
) -> str:
    parts = [
        f'<div style="{_PAGE_STYLE}">',
        f"<h2>Notebook {escape(filename)}</h2>",
    ]
    if notebook_diff is not None:
        parts.extend(_render_notebook_diff(notebook_diff))
    else:
        cells = _cells(notebook)
        if not cells:
            parts.append("<p>No cells.</p>")
        else:
            language = _notebook_language(notebook)
            for index, cell in enumerate(cells, start=1):
                parts.append(_render_cell(index=index, cell=cell, language=language))
    parts.append("</div>")
    return "\n".join(parts)


def _render_notebook_diff(notebook_diff: NotebookDiff) -> list[str]:
    parts = [
        "<h3>Notebook diff</h3>",
        f"<p>{escape(notebook_diff.summary)}</p>",
    ]
    parts.extend(entry.html for entry in notebook_diff.entries)
    return parts


def _render_cell(*, index: int, cell: Mapping[str, object], language: str) -> str:
    cell_type = _string(cell.get("cell_type")) or "cell"
    source = _join_text(cell.get("source")) or ""
    title = f"Cell {index} ({cell_type})"
    parts = [
        f'<section style="{_CELL_STYLE}">',
        f'<h3 style="{_HEADING_STYLE}">{escape(title)}</h3>',
    ]
    if cell_type == "markdown":
        parts.extend(
            [
                f'<h4 style="{_SUBHEADING_STYLE}">Markdown</h4>',
                f'<div style="{_MARKDOWN_STYLE}">{escape(source)}</div>',
            ]
        )
    else:
        parts.extend(
            [
                f'<h4 style="{_SUBHEADING_STYLE}">Source</h4>',
                (
                    f'<pre style="{_SOURCE_STYLE}">'
                    f"{_highlight_code(source, language)}</pre>"
                ),
            ]
        )
    if cell_type == "code":
        parts.extend(_render_outputs(cell.get("outputs")))
    parts.append("</section>")
    return "\n".join(parts)


def _render_outputs(value: object) -> list[str]:
    outputs = _outputs(value)
    parts = [f'<h4 style="{_SUBHEADING_STYLE}">Outputs</h4>']
    if not outputs:
        parts.append("<p>No outputs.</p>")
        return parts
    for output in outputs:
        parts.append(_render_output(output))
    return parts


def _render_output(output: Mapping[str, object]) -> str:
    output_type = _string(output.get("output_type"))
    if output_type == "stream":
        return _render_text_output(
            label=f"stream ({_string(output.get('name')) or 'stream'})",
            text=_join_text(output.get("text")) or "",
        )
    if output_type in ("display_data", "execute_result"):
        data = _as_dict(output.get("data")) or {}
        label = output_type.replace("_", " ")
        return _render_mime_bundle(label=label, data=data)
    if output_type == "error":
        return _render_text_output(label="error", text=_error_text(output))
    return _render_text_output(label=output_type or "output", text="")


def _render_text_output(*, label: str, text: str) -> str:
    parts = [
        f'<div style="{_OUTPUT_STYLE}">',
        f'<div style="{_OUTPUT_LABEL_STYLE}">{escape(label)}</div>',
    ]
    if text:
        parts.append(f'<pre style="{_SOURCE_STYLE}">{escape(text)}</pre>')
    parts.append("</div>")
    return "\n".join(parts)


def _render_mime_bundle(*, label: str, data: Mapping[str, object]) -> str:
    parts = [
        f'<div style="{_OUTPUT_STYLE}">',
        f'<div style="{_OUTPUT_LABEL_STYLE}">{escape(label)}</div>',
    ]
    text = _join_text(data.get("text/plain"))
    if text:
        parts.append(f'<pre style="{_SOURCE_STYLE}">{escape(text)}</pre>')
    for mime_type in _IMAGE_MIME_TYPES:
        image = _image_data_uri(mime_type, data.get(mime_type))
        if image is not None:
            alt = f"{mime_type} output"
            parts.append(
                f'<img style="{_IMAGE_STYLE}" src="{image}" alt="{escape(alt)}">'
            )
    parts.append("</div>")
    return "\n".join(parts)


def _highlight_code(source: str, language: str) -> str:
    if not source:
        return ""
    if highlighted := _highlight_with_pygments(source, language):
        return highlighted
    return _highlight_without_pygments(source, language)


def _highlight_with_pygments(source: str, language: str) -> str | None:
    try:
        from pygments import highlight
        from pygments.formatters.html import HtmlFormatter
        from pygments.lexers import get_lexer_by_name
        from pygments.util import ClassNotFound
    except ImportError:  # pragma: no cover - exercised only without Pygments.
        return None
    try:
        lexer = get_lexer_by_name(language or "python")
    except ClassNotFound:
        return None
    formatter = HtmlFormatter(nowrap=True, noclasses=True)
    return highlight(source, lexer, formatter)


def _highlight_without_pygments(source: str, language: str) -> str:
    if language.lower() not in {"py", "python", "python3"}:
        return escape(source)
    return _highlight_python(source)


def _highlight_python(source: str) -> str:
    try:
        tokens = tuple(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError:
        return escape(source)
    line_offsets = _line_offsets(source)
    cursor = 0
    parts: list[str] = []
    for token in tokens:
        if token.type in (tokenize.ENCODING, tokenize.ENDMARKER):
            continue
        start = _offset(line_offsets, token.start, len(source))
        end = _offset(line_offsets, token.end, len(source))
        if start > cursor:
            parts.append(escape(source[cursor:start]))
        token_html = escape(source[start:end])
        if style := _python_token_style(token):
            parts.append(f'<span style="{style}">{token_html}</span>')
        else:
            parts.append(token_html)
        cursor = end
    if cursor < len(source):
        parts.append(escape(source[cursor:]))
    return "".join(parts)


def _python_token_style(token: tokenize.TokenInfo) -> str | None:
    if token.type == tokenize.COMMENT:
        return _TOKEN_STYLES["comment"]
    if token.type == tokenize.STRING:
        return _TOKEN_STYLES["string"]
    if token.type == tokenize.NUMBER:
        return _TOKEN_STYLES["number"]
    if token.type == tokenize.OP:
        return _TOKEN_STYLES["operator"]
    if token.type == tokenize.NAME:
        if keyword.iskeyword(token.string):
            return _TOKEN_STYLES["keyword"]
        if token.string in _PYTHON_NAMES:
            return _TOKEN_STYLES["builtin"]
    return None


def _line_offsets(source: str) -> tuple[int, ...]:
    offsets = [0]
    total = 0
    for line in source.splitlines(keepends=True):
        total += len(line)
        offsets.append(total)
    return tuple(offsets)


def _offset(
    line_offsets: tuple[int, ...], position: tuple[int, int], source_length: int
) -> int:
    row, column = position
    if row <= 0:
        return 0
    if row - 1 >= len(line_offsets):
        return source_length
    return min(line_offsets[row - 1] + column, source_length)


def _image_data_uri(mime_type: str, value: object) -> str | None:
    payload = _join_text(value)
    if not payload:
        return None
    if mime_type == "image/svg+xml":
        encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    else:
        encoded = "".join(payload.split())
    return f"data:{escape(mime_type)};base64,{escape(encoded)}"


def _error_text(output: Mapping[str, object]) -> str:
    ename = _string(output.get("ename"))
    evalue = _string(output.get("evalue"))
    header = ": ".join(part for part in (ename, evalue) if part)
    traceback = _join_text(output.get("traceback")) or ""
    return "\n".join(part for part in (header, traceback) if part)


def _cells(notebook: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    cells = notebook.get("cells")
    if not isinstance(cells, list):
        return ()
    return tuple(
        normalized for cell in cells if (normalized := _as_dict(cell)) is not None
    )


def _notebook_language(notebook: Mapping[str, object]) -> str:
    metadata = _as_dict(notebook.get("metadata")) or {}
    language_info = _as_dict(metadata.get("language_info")) or {}
    kernelspec = _as_dict(metadata.get("kernelspec")) or {}
    return (
        _string(language_info.get("name"))
        or _string(kernelspec.get("language"))
        or "python"
    )


def _outputs(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        normalized for item in value if (normalized := _as_dict(item)) is not None
    )


def _as_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return {str(key): nested for key, nested in value.items()}


def _join_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        parts: list[str] = []
        for part in value:
            if not isinstance(part, str):
                return None
            parts.append(part)
        return "".join(parts)
    return None


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""
