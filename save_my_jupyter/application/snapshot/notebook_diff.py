"""Rich notebook diff rendering (target CONTENT, contract C-CONTENT-06).

The renderer compares user-visible notebook structure while dropping known
Jupyter churn: cell ids, execution counts, cell/notebook metadata, and raw
base64 image payload changes. It returns LabArchives-ready HTML entries so the
snapshot can include a readable cell-by-cell notebook page instead of only a raw
``.ipynb`` attachment.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import unified_diff
from html import escape

from save_my_jupyter.domain.delivery import NotebookDiff, NotebookDiffEntry

_PAGE_NAME = "01 Notebook Diff"
_IMAGE_MIME_TYPES = (
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/gif",
    "image/webp",
    "image/svg+xml",
)
_CELL_STYLE = (
    "border:1px solid #d0d7de;border-radius:6px;margin:12px 0;"
    "padding:12px;background:#fff;"
)
_HEADING_STYLE = "margin:0 0 10px 0;font-size:16px;"
_SUBHEADING_STYLE = "margin:12px 0 6px 0;font-size:13px;"
_PRE_STYLE = (
    "white-space:pre-wrap;margin:0;padding:10px;background:#f6f8fa;"
    "border:1px solid #d8dee4;border-radius:4px;"
)
_OUTPUT_STYLE = (
    "border:1px solid #d8dee4;border-radius:4px;margin:8px 0;padding:8px;"
    "background:#fbfbfb;"
)
_OUTPUT_LABEL_STYLE = "font-weight:600;margin-bottom:6px;"
_DIFF_PRE_STYLE = (
    "white-space:pre-wrap;margin:0;padding:0;background:#fff;"
    "border:1px solid #d8dee4;border-radius:4px;"
    "font-family:ui-monospace,SFMono-Regular,Consolas,Liberation Mono,Menlo,"
    "monospace;font-size:12px;"
)
_DIFF_LINE_STYLE = "display:block;padding:2px 6px;"
_IMAGE_STYLE = "display:block;max-width:100%;height:auto;margin:8px 0;"


@dataclass(frozen=True, slots=True)
class _ImageOutput:
    mime_type: str
    data: str


@dataclass(frozen=True, slots=True)
class _Output:
    output_type: str
    label: str
    text: str
    images: tuple[_ImageOutput, ...]

    def comparison_key(self) -> tuple[object, ...]:
        image_mimes = tuple(image.mime_type for image in self.images)
        return (self.output_type, self.label, self.text, image_mimes)

    def comparison_lines(self) -> list[str]:
        lines = [self.label]
        if self.text:
            lines.extend(self.text.splitlines() or [""])
        for image in self.images:
            lines.append(f"{image.mime_type} output")
        return lines


@dataclass(frozen=True, slots=True)
class _Cell:
    cell_type: str
    source: str
    outputs: tuple[_Output, ...]

    def comparison_key(self) -> tuple[object, ...]:
        return (
            self.cell_type,
            self.source,
            tuple(output.comparison_key() for output in self.outputs),
        )


def render_notebook_diff(
    before: Mapping[str, object], after: Mapping[str, object]
) -> NotebookDiff | None:
    before_cells = _without_trailing_empty_cells(
        [_normalized_cell(cell) for cell in _cells(before)]
    )
    after_cells = _without_trailing_empty_cells(
        [_normalized_cell(cell) for cell in _cells(after)]
    )
    max_len = max(len(before_cells), len(after_cells))
    statuses: list[str] = []
    changed_count = 0

    for index in range(max_len):
        before_cell = before_cells[index] if index < len(before_cells) else None
        after_cell = after_cells[index] if index < len(after_cells) else None
        status = _cell_status(before_cell, after_cell)
        statuses.append(status)
        if status != "unchanged":
            changed_count += 1

    if changed_count == 0:
        return None

    entries: list[NotebookDiffEntry] = []
    for index, status in enumerate(statuses):
        before_cell = before_cells[index] if index < len(before_cells) else None
        after_cell = after_cells[index] if index < len(after_cells) else None
        title = _cell_title(index=index, status=status, cell=after_cell or before_cell)
        source_diff_html = (
            _render_line_diff(_source_lines(before_cell), _source_lines(after_cell))
            if status != "unchanged"
            else None
        )
        output_diff_html = None
        if before_cell is not None and after_cell is not None and status == "changed":
            before_lines = _output_lines(before_cell.outputs)
            after_lines = _output_lines(after_cell.outputs)
            if before_lines != after_lines:
                output_diff_html = _render_line_diff(before_lines, after_lines)
        entries.append(
            NotebookDiffEntry(
                title=title,
                cell_index=index,
                status=status,
                source_diff_html=source_diff_html,
                output_diff_html=output_diff_html,
                html=_render_cell_entry(
                    title=title,
                    status=status,
                    before_cell=before_cell,
                    after_cell=after_cell,
                    source_diff_html=source_diff_html,
                    output_diff_html=output_diff_html,
                ),
            )
        )

    total = max_len if max_len else len(after_cells)
    summary = f"{changed_count} of {total} cells changed."
    return NotebookDiff(page_name=_PAGE_NAME, summary=summary, entries=tuple(entries))


def _cell_status(before_cell: _Cell | None, after_cell: _Cell | None) -> str:
    if before_cell is None:
        return "added"
    if after_cell is None:
        return "removed"
    if before_cell.comparison_key() != after_cell.comparison_key():
        return "changed"
    return "unchanged"


def _without_trailing_empty_cells(cells: list[_Cell]) -> list[_Cell]:
    while cells and _is_empty_cell(cells[-1]):
        cells.pop()
    return cells


def _is_empty_cell(cell: _Cell) -> bool:
    return not cell.source.strip() and not cell.outputs


def _cell_title(*, index: int, status: str, cell: _Cell | None) -> str:
    suffix = f" ({cell.cell_type})" if cell is not None and cell.cell_type else ""
    if status == "added":
        return f"Cell {index + 1} added{suffix}"
    if status == "removed":
        return f"Cell {index + 1} removed{suffix}"
    if status == "changed":
        return f"Cell {index + 1} changed{suffix}"
    return f"Cell {index + 1}{suffix}"


def _render_cell_entry(
    *,
    title: str,
    status: str,
    before_cell: _Cell | None,
    after_cell: _Cell | None,
    source_diff_html: str | None,
    output_diff_html: str | None,
) -> str:
    display_cell = after_cell or before_cell
    parts = [
        f'<section style="{_CELL_STYLE}">',
        f'<h3 style="{_HEADING_STYLE}">{escape(title)}</h3>',
    ]
    if status == "unchanged":
        parts.extend(
            [
                f'<h4 style="{_SUBHEADING_STYLE}">Source</h4>',
                _render_source(display_cell.source if display_cell else ""),
            ]
        )
    else:
        parts.extend(
            [
                f'<h4 style="{_SUBHEADING_STYLE}">Source diff</h4>',
                source_diff_html or "<p>No changes.</p>",
            ]
        )

    if after_cell is not None:
        parts.extend(_render_outputs_section("Snapshot outputs", after_cell.outputs))
    elif before_cell is not None:
        parts.extend(
            _render_outputs_section("Removed cell outputs", before_cell.outputs)
        )

    if output_diff_html is not None:
        parts.extend(
            [
                f'<h4 style="{_SUBHEADING_STYLE}">Output diff</h4>',
                output_diff_html,
            ]
        )

    parts.append("</section>")
    return "\n".join(parts)


def _render_source(source: str) -> str:
    return f'<pre style="{_PRE_STYLE}">{escape(source)}</pre>'


def _render_outputs_section(label: str, outputs: tuple[_Output, ...]) -> list[str]:
    parts = [f'<h4 style="{_SUBHEADING_STYLE}">{escape(label)}</h4>']
    if not outputs:
        parts.append("<p>No outputs.</p>")
        return parts
    for output in outputs:
        parts.append(_render_output(output))
    return parts


def _render_output(output: _Output) -> str:
    parts = [
        f'<div style="{_OUTPUT_STYLE}">',
        f'<div style="{_OUTPUT_LABEL_STYLE}">{escape(output.label)}</div>',
    ]
    if output.text:
        parts.append(f'<pre style="{_PRE_STYLE}">{escape(output.text)}</pre>')
    for image in output.images:
        src = f"data:{escape(image.mime_type)};base64,{escape(image.data)}"
        alt = f"{image.mime_type} output"
        parts.append(f'<img style="{_IMAGE_STYLE}" src="{src}" alt="{escape(alt)}">')
    parts.append("</div>")
    return "\n".join(parts)


def _render_line_diff(before_lines: Sequence[str], after_lines: Sequence[str]) -> str:
    diff_lines = list(
        unified_diff(
            list(before_lines),
            list(after_lines),
            fromfile="HEAD",
            tofile="snapshot",
            lineterm="",
        )
    )
    if not diff_lines:
        return "<p>No changes.</p>"
    if (
        len(diff_lines) >= 2
        and diff_lines[0].startswith("--- ")
        and diff_lines[1].startswith("+++ ")
    ):
        diff_lines = diff_lines[2:]
    rows = "".join(_render_diff_line(line) for line in diff_lines)
    return f'<pre style="{_DIFF_PRE_STYLE}">{rows}</pre>'


def _render_diff_line(line: str) -> str:
    if line.startswith("+") and not line.startswith("+++"):
        style = "background:#e6ffed;color:#116329;"
    elif line.startswith("-") and not line.startswith("---"):
        style = "background:#ffebe9;color:#82071e;"
    elif line.startswith("@@"):
        style = "background:#ddf4ff;color:#0550ae;"
    elif line.startswith(("---", "+++")):
        style = "background:#f6f8fa;color:#57606a;"
    else:
        style = "background:#fff;color:#24292f;"
    return f'<span style="{_DIFF_LINE_STYLE}{style}">{escape(line)}</span>'


def _source_lines(cell: _Cell | None) -> list[str]:
    if cell is None:
        return []
    return cell.source.splitlines() or [""]


def _output_lines(outputs: tuple[_Output, ...]) -> list[str]:
    lines: list[str] = []
    for output in outputs:
        lines.extend(output.comparison_lines())
    return lines


def _normalized_cell(cell: Mapping[str, object]) -> _Cell:
    return _Cell(
        cell_type=_string(cell.get("cell_type")),
        source=_join_text(cell.get("source")) or "",
        outputs=_normalized_outputs(cell.get("outputs")),
    )


def _normalized_outputs(value: object) -> tuple[_Output, ...]:
    if not isinstance(value, list):
        return ()
    outputs: list[_Output] = []
    for output in value:
        normalized = _as_dict(output)
        if normalized is None:
            continue
        output_type = _string(normalized.get("output_type"))
        if output_type == "stream":
            name = _string(normalized.get("name")) or "stream"
            outputs.append(
                _Output(
                    output_type=output_type,
                    label=f"stream ({name})",
                    text=_join_text(normalized.get("text")) or "",
                    images=(),
                )
            )
        elif output_type in ("display_data", "execute_result"):
            data = _as_dict(normalized.get("data")) or {}
            outputs.append(
                _Output(
                    output_type=output_type,
                    label=output_type.replace("_", " "),
                    text=_join_text(data.get("text/plain")) or "",
                    images=_image_outputs(data),
                )
            )
        elif output_type == "error":
            outputs.append(
                _Output(
                    output_type=output_type,
                    label="error",
                    text=_error_text(normalized),
                    images=(),
                )
            )
    return tuple(outputs)


def _error_text(output: Mapping[str, object]) -> str:
    ename = _string(output.get("ename"))
    evalue = _string(output.get("evalue"))
    header = ": ".join(part for part in (ename, evalue) if part)
    traceback = _join_text(output.get("traceback")) or ""
    return "\n".join(part for part in (header, traceback) if part)


def _image_outputs(data: Mapping[str, object]) -> tuple[_ImageOutput, ...]:
    images: list[_ImageOutput] = []
    for mime_type in _IMAGE_MIME_TYPES:
        raw = _join_text(data.get(mime_type))
        if raw:
            images.append(
                _ImageOutput(mime_type=mime_type, data=_image_data(mime_type, raw))
            )
    return tuple(images)


def _image_data(mime_type: str, raw: str) -> str:
    if mime_type == "image/svg+xml":
        return base64.b64encode(raw.encode("utf-8")).decode("ascii")
    return "".join(raw.split())


def _cells(notebook: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    cells = notebook.get("cells")
    if not isinstance(cells, list):
        return ()
    return tuple(
        normalized for cell in cells if (normalized := _as_dict(cell)) is not None
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
