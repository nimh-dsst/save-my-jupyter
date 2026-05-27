from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal, cast

from dulwich.object_store import tree_lookup_path
from dulwich.objects import Blob, Commit
from dulwich.repo import Repo

type JsonObject = dict[str, object]

_PREFERRED_TEXT_MIME_TYPES = (
    "text/plain",
    "text/markdown",
    "text/html",
    "application/json",
)


@dataclass(frozen=True, slots=True)
class NotebookCellState:
    cell_type: str
    cell_id: str | None
    source: str
    outputs: str


@dataclass(frozen=True, slots=True)
class NotebookCellChange:
    status: Literal["added", "removed", "changed"]
    old_index: int | None
    new_index: int | None
    old_cell: NotebookCellState | None
    new_cell: NotebookCellState | None


@dataclass(frozen=True, slots=True)
class NotebookDiff:
    path: str
    changes: tuple[NotebookCellChange, ...]


def build_notebook_diff(
    *,
    notebook_path: str | Path,
    relative_path: str,
    repo_root: str | Path | None,
    base_commit: str | None,
) -> NotebookDiff | None:
    current_model = _load_json_mapping(Path(notebook_path).resolve())
    if current_model is None:
        return None

    previous_model = (
        _load_repo_notebook(
            repo_root=Path(repo_root).resolve(),
            relative_path=relative_path,
            commit_hash=base_commit,
        )
        if repo_root is not None and base_commit is not None
        else None
    )

    previous_cells = _extract_cells(previous_model)
    current_cells = _extract_cells(current_model)
    changes = _diff_cells(previous_cells, current_cells)
    if not changes:
        return None
    return NotebookDiff(
        path=relative_path,
        changes=tuple(changes),
    )


def _load_repo_notebook(
    *,
    repo_root: Path,
    relative_path: str,
    commit_hash: str,
) -> JsonObject | None:
    try:
        with Repo(str(repo_root)) as repo:
            commit = repo[commit_hash.encode("ascii")]
            if not isinstance(commit, Commit):
                return None
            _mode, object_id = tree_lookup_path(
                repo.object_store.__getitem__,
                commit.tree,
                relative_path.encode("utf-8"),
            )
            blob = repo.object_store[object_id]
    except (KeyError, OSError, UnicodeEncodeError):
        return None

    if not isinstance(blob, Blob):
        return None
    try:
        payload = blob.data.decode("utf-8")
    except UnicodeDecodeError:
        return None

    return _normalize_json_mapping(payload)


def _load_json_mapping(path: Path) -> JsonObject | None:
    try:
        payload = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return _normalize_json_mapping(payload)


def _normalize_json_mapping(payload: str) -> JsonObject | None:
    try:
        loaded = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, Mapping):
        return None
    return {str(key): value for key, value in loaded.items()}


def _extract_cells(model: Mapping[str, object] | None) -> tuple[NotebookCellState, ...]:
    if model is None:
        return ()

    raw_cells = model.get("cells")
    if not isinstance(raw_cells, list):
        return ()

    cells: list[NotebookCellState] = []
    for raw_cell in raw_cells:
        cell = _as_str_mapping(raw_cell)
        if cell is None:
            continue
        cell_type = cell.get("cell_type")
        source = _string_payload(cell.get("source"))
        cell_id = cell.get("id")
        cells.append(
            NotebookCellState(
                cell_type=cell_type if isinstance(cell_type, str) else "unknown",
                cell_id=cell_id if isinstance(cell_id, str) else None,
                source=source or "",
                outputs=_render_outputs(cell),
            )
        )
    return tuple(cells)


def _render_outputs(cell: Mapping[str, object]) -> str:
    raw_outputs = cell.get("outputs")
    if not isinstance(raw_outputs, list):
        return ""

    sections: list[str] = []
    for output_index, raw_output in enumerate(raw_outputs, start=1):
        output = _as_str_mapping(raw_output)
        if output is None:
            continue
        rendered = _render_output(output)
        if rendered == "":
            continue
        sections.append(f"Output {output_index}\n{rendered}")
    return "\n\n".join(sections)


def _render_output(output: Mapping[str, object]) -> str:
    sections: list[str] = []

    stream_text = _string_payload(output.get("text"))
    if stream_text not in (None, ""):
        sections.append(f"stream\n{stream_text}")

    traceback = output.get("traceback")
    if isinstance(traceback, list):
        rendered_traceback = "".join(
            line for line in traceback if isinstance(line, str)
        )
        if rendered_traceback != "":
            sections.append(f"error\n{rendered_traceback}")

    data = _as_str_mapping(output.get("data"))
    if data is not None:
        for mime_type in _iter_text_mime_types(data):
            rendered = _string_payload(data.get(mime_type))
            if rendered in (None, ""):
                continue
            sections.append(f"{mime_type}\n{rendered}")

    return "\n\n".join(sections)


def _iter_text_mime_types(data: Mapping[str, object]) -> tuple[str, ...]:
    normalized = {str(key): value for key, value in data.items()}
    ordered = [
        mime_type for mime_type in _PREFERRED_TEXT_MIME_TYPES if mime_type in normalized
    ]
    ordered.extend(
        mime_type
        for mime_type in sorted(normalized)
        if mime_type not in ordered
        and (
            mime_type.startswith("text/")
            or mime_type in {"application/json", "application/vnd.jupyter.stderr"}
        )
    )
    return tuple(ordered)


def _as_str_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast("Mapping[str, object]", value)


def _string_payload(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        string_parts = [part for part in value if isinstance(part, str)]
        if len(string_parts) != len(value):
            return None
        return "".join(string_parts)
    return None


def _diff_cells(
    previous_cells: tuple[NotebookCellState, ...],
    current_cells: tuple[NotebookCellState, ...],
) -> list[NotebookCellChange]:
    changes: list[NotebookCellChange] = []
    matcher = SequenceMatcher(
        a=[_alignment_token(cell) for cell in previous_cells],
        b=[_alignment_token(cell) for cell in current_cells],
        autojunk=False,
    )

    for tag, old_start, old_stop, new_start, new_stop in matcher.get_opcodes():
        if tag == "equal":
            for old_index, new_index in zip(
                range(old_start, old_stop),
                range(new_start, new_stop),
                strict=True,
            ):
                change = _compare_cells(
                    old_index=old_index,
                    previous_cell=previous_cells[old_index],
                    new_index=new_index,
                    current_cell=current_cells[new_index],
                )
                if change is not None:
                    changes.append(change)
            continue

        if tag == "replace":
            shared = min(old_stop - old_start, new_stop - new_start)
            for offset in range(shared):
                changes.append(
                    NotebookCellChange(
                        status="changed",
                        old_index=old_start + offset,
                        new_index=new_start + offset,
                        old_cell=previous_cells[old_start + offset],
                        new_cell=current_cells[new_start + offset],
                    )
                )
            for old_index in range(old_start + shared, old_stop):
                changes.append(
                    NotebookCellChange(
                        status="removed",
                        old_index=old_index,
                        new_index=None,
                        old_cell=previous_cells[old_index],
                        new_cell=None,
                    )
                )
            for new_index in range(new_start + shared, new_stop):
                changes.append(
                    NotebookCellChange(
                        status="added",
                        old_index=None,
                        new_index=new_index,
                        old_cell=None,
                        new_cell=current_cells[new_index],
                    )
                )
            continue

        if tag == "delete":
            for old_index in range(old_start, old_stop):
                changes.append(
                    NotebookCellChange(
                        status="removed",
                        old_index=old_index,
                        new_index=None,
                        old_cell=previous_cells[old_index],
                        new_cell=None,
                    )
                )
            continue

        if tag == "insert":
            for new_index in range(new_start, new_stop):
                changes.append(
                    NotebookCellChange(
                        status="added",
                        old_index=None,
                        new_index=new_index,
                        old_cell=None,
                        new_cell=current_cells[new_index],
                    )
                )

    return changes


def _compare_cells(
    *,
    old_index: int,
    previous_cell: NotebookCellState,
    new_index: int,
    current_cell: NotebookCellState,
) -> NotebookCellChange | None:
    if (
        previous_cell.cell_type == current_cell.cell_type
        and previous_cell.source == current_cell.source
        and previous_cell.outputs == current_cell.outputs
    ):
        return None
    return NotebookCellChange(
        status="changed",
        old_index=old_index,
        new_index=new_index,
        old_cell=previous_cell,
        new_cell=current_cell,
    )


def _alignment_token(cell: NotebookCellState) -> str:
    if cell.cell_id not in (None, ""):
        return f"id:{cell.cell_id}"

    first_line = next(
        (line.strip() for line in cell.source.splitlines() if line.strip() != ""),
        "",
    )
    return f"{cell.cell_type}:{first_line[:80]}"
