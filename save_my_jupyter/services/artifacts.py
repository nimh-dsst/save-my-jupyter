from __future__ import annotations

import base64
import binascii
import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

from save_my_jupyter.domain import (
    ArtifactRef,
    DiffArtifact,
    FigureArtifact,
    FileArtifact,
    MimeType,
    NotebookArtifact,
    RelativeRepoPath,
    RelativeWatchPath,
    ResolvedSnapshotPlan,
)
from save_my_jupyter.errors import ArtifactCollectionError
from save_my_jupyter.parsing import normalize_path
from save_my_jupyter.watch_paths import resolve_watch_files

_DIFF_PATH_PATTERN = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_DIFF_ATTACHMENT_MAX_LENGTH = 1_000_000
_FILE_UPLOAD_MAX_BYTES = 25 * 1024 * 1024
_NOTEBOOK_UPLOAD_MAX_BYTES = 50 * 1024 * 1024
_BINARY_FIGURE_MIME_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
}
_IMAGE_SUFFIXES = frozenset(
    {
        ".avif",
        ".bmp",
        ".gif",
        ".jpeg",
        ".jpg",
        ".png",
        ".svg",
        ".tif",
        ".tiff",
        ".webp",
    }
)
_PREFERRED_SUMMARY_MIME_TYPES: tuple[str, ...] = ("text/plain",)
_SPECIAL_FILE_MIME_TYPES: dict[str, str] = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".tsv": "text/tab-separated-values",
    ".txt": "text/plain",
}
_TEXT_FIGURE_MIME_TYPES: dict[str, str] = {
    "image/svg+xml": "svg",
}
_VALUE_SUMMARY_MAX_LENGTH = 5000


@dataclass(frozen=True, slots=True)
class NotebookOutputRef:
    cell_id: str | None
    cell_index: int
    output: dict[str, object]
    output_index: int


@dataclass(frozen=True, slots=True)
class OutputTextSummary:
    source: str
    text: str


class DocumentArtifactCollector:
    def collect_notebook_artifact(
        self,
        plan: ResolvedSnapshotPlan,
    ) -> NotebookArtifact | None:
        if not plan.effective_config.include_notebook_file:
            return None
        notebook_path = Path(plan.request.notebook_context.notebook_path).resolve()
        _validate_upload_size(
            notebook_path,
            max_bytes=_NOTEBOOK_UPLOAD_MAX_BYTES,
            code="notebook_artifact_too_large",
        )
        return NotebookArtifact(
            display_name=notebook_path.name,
            mime_type=MimeType("application/x-ipynb+json"),
            local_path=notebook_path,
            relative_path=plan.repo.relative_notebook_path,
        )

    def collect_figure_artifacts(
        self,
        plan: ResolvedSnapshotPlan,
    ) -> tuple[FigureArtifact, ...]:
        figures: list[FigureArtifact] = []
        figure_index = 1
        for output_ref in _iter_notebook_outputs(plan):
            data = _normalize_object_dict(output_ref.output.get("data"))
            if data is None:
                continue

            figure = _extract_figure_artifact(data, output_ref, figure_index)
            if figure is None:
                continue
            figures.append(figure)
            figure_index += 1

        return tuple(figures)

    def collect_file_artifacts(
        self,
        plan: ResolvedSnapshotPlan,
    ) -> tuple[FileArtifact, ...]:
        if not plan.effective_config.watched_paths:
            return ()

        capture_root = _resolve_capture_root(plan)
        file_artifacts: dict[str, FileArtifact] = {}
        for file_path in _iter_watched_files(plan, capture_root):
            _validate_upload_size(
                file_path,
                max_bytes=_FILE_UPLOAD_MAX_BYTES,
                code="watched_file_artifact_too_large",
            )
            normalized_relative_path = normalize_path(
                str(file_path.relative_to(capture_root)).replace("\\", "/")
            )
            relative_path = _make_file_relative_path(
                normalized_relative_path,
                has_repo_root=plan.repo.repo_root is not None,
            )
            try:
                bytes_payload = file_path.read_bytes()
            except OSError as exc:
                raise ArtifactCollectionError(
                    "Unable to read watched file artifact.",
                    code="watched_file_artifact_read_failed",
                    context={"path": str(file_path)},
                ) from exc
            file_artifacts[normalized_relative_path] = FileArtifact(
                display_name=file_path.name,
                mime_type=MimeType(_guess_file_mime_type(file_path)),
                local_path=file_path,
                relative_path=relative_path,
                bytes_payload=bytes_payload,
            )

        return tuple(file_artifacts[key] for key in sorted(file_artifacts))

    def collect_diff_artifact(
        self,
        plan: ResolvedSnapshotPlan,
        diff_text: str | None,
    ) -> DiffArtifact | None:
        if diff_text is None or diff_text == "":
            return None
        filtered_diff_text = _filter_diff_attachment_text(plan, diff_text)
        if filtered_diff_text is None:
            return None
        return DiffArtifact(
            display_name="working-tree.patch",
            mime_type=MimeType("text/x-diff"),
            diff_text=filtered_diff_text,
        )

    def collect_value_summary(self, plan: ResolvedSnapshotPlan) -> str | None:
        output_sections = [
            section
            for output_ref in _iter_notebook_outputs(plan)
            if (section := _format_output_summary(output_ref)) is not None
        ]
        if not output_sections:
            return None
        return _truncate_text(
            "\n\n".join(["Result Summary", *output_sections]),
            _VALUE_SUMMARY_MAX_LENGTH,
        )

    def collect_all(
        self,
        plan: ResolvedSnapshotPlan,
        diff_text: str | None,
        *,
        file_artifacts: tuple[FileArtifact, ...] | None = None,
    ) -> tuple[ArtifactRef, ...]:
        artifacts: list[ArtifactRef] = []
        notebook_artifact = self.collect_notebook_artifact(plan)
        if notebook_artifact is not None:
            artifacts.append(notebook_artifact)
        artifacts.extend(self.collect_figure_artifacts(plan))
        artifacts.extend(
            file_artifacts
            if file_artifacts is not None
            else self.collect_file_artifacts(plan)
        )
        diff_artifact = self.collect_diff_artifact(plan, diff_text)
        if diff_artifact is not None:
            artifacts.append(diff_artifact)
        return tuple(artifacts)


def _extract_figure_artifact(
    data: dict[str, object],
    output_ref: NotebookOutputRef,
    figure_index: int,
) -> FigureArtifact | None:
    for mime_type, extension in _BINARY_FIGURE_MIME_TYPES.items():
        payload = _normalize_string_payload(data.get(mime_type))
        if payload is None:
            continue
        return FigureArtifact(
            display_name=_figure_display_name(output_ref, extension),
            mime_type=MimeType(mime_type),
            figure_index=figure_index,
            bytes_payload=base64.b64decode(payload),
        )

    for mime_type, extension in _TEXT_FIGURE_MIME_TYPES.items():
        payload = _normalize_string_payload(data.get(mime_type))
        if payload is None:
            continue
        return FigureArtifact(
            display_name=_figure_display_name(output_ref, extension),
            mime_type=MimeType(mime_type),
            figure_index=figure_index,
            bytes_payload=payload.encode("utf-8"),
        )

    return None


def _figure_display_name(output_ref: NotebookOutputRef, extension: str) -> str:
    if output_ref.cell_id not in (None, ""):
        cell_part = _slugify(output_ref.cell_id)
    else:
        cell_part = f"cell-{output_ref.cell_index + 1:03}"
    return f"figure-{cell_part}-output-{output_ref.output_index + 1:02}.{extension}"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    slug = slug.strip(".-_")
    return slug[:80] or "cell"


def _extract_output_text(output: dict[str, object]) -> OutputTextSummary | None:
    text = output.get("text")
    if isinstance(text, str):
        return OutputTextSummary(
            source='output["text"]',
            text=text,
        )
    if "text" in output and isinstance(output["text"], list):
        return OutputTextSummary(
            source='output["text"]',
            text="".join(line for line in output["text"] if isinstance(line, str)),
        )
    data = _normalize_object_dict(output.get("data"))
    if data is not None:
        text_data = data.get("text/plain")
        if isinstance(text_data, str):
            return OutputTextSummary(
                source='data["text/plain"]',
                text=text_data,
            )
        if isinstance(text_data, list):
            return OutputTextSummary(
                source='data["text/plain"]',
                text="".join(line for line in text_data if isinstance(line, str)),
            )
    return None


def _extract_preferred_output_text(
    output: dict[str, object],
) -> OutputTextSummary | None:
    data = _normalize_object_dict(output.get("data"))
    if data is None:
        return None
    for mime_type in _PREFERRED_SUMMARY_MIME_TYPES:
        text = _normalize_string_payload(data.get(mime_type))
        if text is not None:
            return OutputTextSummary(
                source=f'data["{mime_type}"]',
                text=text,
            )
    return None


def _format_output_summary(output_ref: NotebookOutputRef) -> str | None:
    summary = _extract_preferred_output_text(output_ref.output)
    if summary is None:
        summary = _extract_error_output_text(output_ref.output)
    if summary is None:
        summary = _extract_output_text(output_ref.output)
    if summary is None:
        summary = _extract_image_output_text(output_ref.output)
    if summary is None:
        summary = _extract_non_text_output_summary(output_ref.output)
    if summary is None:
        return None

    location = f"Cell {output_ref.cell_index + 1}"
    if output_ref.cell_id not in (None, ""):
        location = f"{location} (id: {output_ref.cell_id})"
    output_type = output_ref.output.get("output_type")
    output_type_label = (
        str(output_type)
        if isinstance(output_type, str) and output_type != ""
        else "(unknown)"
    )
    header = "\n".join(
        [
            f"Cell        : {location}",
            f"Output      : {output_ref.output_index + 1}",
            f"Output type : {output_type_label}",
            f"Source      : {summary.source}",
            "",
        ]
    )
    return f"{header}{summary.text}"


def _extract_error_output_text(output: dict[str, object]) -> OutputTextSummary | None:
    output_type = output.get("output_type")
    if output_type != "error":
        return None

    lines: list[str] = []
    error_name = output.get("ename")
    error_value = output.get("evalue")
    if isinstance(error_name, str) and error_name != "":
        if isinstance(error_value, str) and error_value != "":
            lines.append(f"{error_name}: {error_value}")
        else:
            lines.append(error_name)
    elif isinstance(error_value, str) and error_value != "":
        lines.append(error_value)

    traceback = output.get("traceback")
    if isinstance(traceback, list):
        rendered_traceback = "".join(
            line for line in traceback if isinstance(line, str)
        )
        if rendered_traceback != "":
            lines.append(rendered_traceback)

    if not lines:
        return None
    return OutputTextSummary(
        source='output["traceback"]',
        text="\n".join(lines),
    )


def _extract_image_output_text(output: dict[str, object]) -> OutputTextSummary | None:
    data = _normalize_object_dict(output.get("data"))
    if data is None:
        return None

    for mime_type in [*_BINARY_FIGURE_MIME_TYPES, *_TEXT_FIGURE_MIME_TYPES]:
        payload = _normalize_string_payload(data.get(mime_type))
        if payload is None:
            continue
        byte_count = _payload_size(payload, encoded=mime_type.startswith("image/"))
        return OutputTextSummary(
            source=f'data["{mime_type}"]',
            text=f"Image output: {mime_type} ({byte_count} bytes).",
        )
    return None


def _extract_non_text_output_summary(
    output: dict[str, object],
) -> OutputTextSummary | None:
    data = _normalize_object_dict(output.get("data"))
    if data is None or not data:
        return None
    return OutputTextSummary(
        source='output["data"]',
        text="Non-text output: " + ", ".join(sorted(data)),
    )


def _payload_size(payload: str, *, encoded: bool) -> int:
    if not encoded:
        return len(payload.encode("utf-8"))
    try:
        return len(base64.b64decode(payload, validate=True))
    except (ValueError, binascii.Error):
        return len(payload.encode("utf-8"))


def _normalize_object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): nested_value for key, nested_value in value.items()}


def _normalize_string_payload(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        string_parts = [part for part in value if isinstance(part, str)]
        if len(string_parts) != len(value):
            return None
        return "".join(string_parts)
    return None


def _filter_diff_attachment_text(
    plan: ResolvedSnapshotPlan,
    diff_text: str,
) -> str | None:
    notebook_path = (
        str(plan.repo.relative_notebook_path)
        if plan.repo.relative_notebook_path is not None
        else None
    )
    sections = _split_patch_sections(diff_text)
    if not sections:
        return _truncate_diff_attachment(diff_text)

    kept_sections: list[str] = []
    for section in sections:
        relative_path = _patch_section_path(section)
        if relative_path is None:
            kept_sections.append(section)
            continue
        if relative_path == notebook_path and relative_path.endswith(".ipynb"):
            continue
        if _is_image_path(relative_path):
            continue
        kept_sections.append(section)

    if not kept_sections:
        return None
    return _truncate_diff_attachment("\n\n".join(kept_sections))


def _split_patch_sections(diff_text: str) -> tuple[str, ...]:
    sections: list[list[str]] = []
    current_lines: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if current_lines:
                sections.append(current_lines)
            current_lines = [line]
            continue
        if current_lines:
            current_lines.append(line)
    if current_lines:
        sections.append(current_lines)
    return tuple("\n".join(lines).strip() for lines in sections)


def _patch_section_path(section: str) -> str | None:
    first_line = section.splitlines()[0] if section else ""
    match = _DIFF_PATH_PATTERN.match(first_line)
    if match is None:
        return None
    return normalize_path(match.group(2))


def _is_image_path(path: str) -> bool:
    return Path(path).suffix.lower() in _IMAGE_SUFFIXES


def _truncate_diff_attachment(diff_text: str) -> str:
    if len(diff_text) <= _DIFF_ATTACHMENT_MAX_LENGTH:
        return diff_text
    omitted = len(diff_text) - _DIFF_ATTACHMENT_MAX_LENGTH
    suffix = f"\n\n[Diff attachment truncated; omitted {omitted} characters.]"
    return diff_text[: _DIFF_ATTACHMENT_MAX_LENGTH - len(suffix)] + suffix


def _truncate_text(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[:max_length]


def _validate_upload_size(path: Path, *, max_bytes: int, code: str) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ArtifactCollectionError(
            "Unable to inspect artifact size.",
            code="artifact_size_check_failed",
            context={"path": str(path)},
        ) from exc
    if size <= max_bytes:
        return
    raise ArtifactCollectionError(
        "Artifact exceeds the configured upload guardrail.",
        code=code,
        context={
            "limit_bytes": str(max_bytes),
            "path": str(path),
            "size_bytes": str(size),
        },
    )


def _load_notebook_model(plan: ResolvedSnapshotPlan) -> dict[str, object]:
    notebook_path = Path(plan.request.notebook_context.notebook_path).resolve()
    try:
        loaded = json.loads(notebook_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactCollectionError(
            "Unable to read notebook artifacts.",
            code="notebook_artifact_parse_failed",
            context={"path": str(notebook_path)},
        ) from exc
    return _normalize_object_dict(loaded) or {}


def _iter_notebook_outputs(
    plan: ResolvedSnapshotPlan,
) -> tuple[NotebookOutputRef, ...]:
    notebook_model = _load_notebook_model(plan)
    outputs: list[NotebookOutputRef] = []
    cells = notebook_model.get("cells")
    if not isinstance(cells, list):
        return ()
    for cell_index, cell in enumerate(cells):
        cell_dict = _normalize_object_dict(cell)
        if cell_dict is None:
            continue
        cell_id = cell_dict.get("id")
        cell_outputs = cell_dict.get("outputs")
        if not isinstance(cell_outputs, list):
            continue
        for output_index, output in enumerate(cell_outputs):
            output_dict = _normalize_object_dict(output)
            if output_dict is not None:
                outputs.append(
                    NotebookOutputRef(
                        cell_id=str(cell_id) if isinstance(cell_id, str) else None,
                        cell_index=cell_index,
                        output=output_dict,
                        output_index=output_index,
                    )
                )
    return tuple(outputs)


def _resolve_capture_root(plan: ResolvedSnapshotPlan) -> Path:
    if plan.repo.repo_root is not None:
        return Path(plan.repo.repo_root).resolve()
    return Path(plan.request.notebook_context.notebook_path).resolve().parent


def _iter_watched_files(
    plan: ResolvedSnapshotPlan,
    capture_root: Path,
) -> tuple[Path, ...]:
    return resolve_watch_files(
        capture_root=capture_root,
        repo_root=(
            Path(plan.repo.repo_root).resolve()
            if plan.repo.repo_root is not None
            else None
        ),
        watch_paths=plan.effective_config.watched_paths,
    )


def _make_file_relative_path(
    normalized_relative_path: str,
    *,
    has_repo_root: bool,
) -> RelativeRepoPath | RelativeWatchPath:
    if has_repo_root:
        return RelativeRepoPath(normalized_relative_path)
    return RelativeWatchPath(normalized_relative_path)


def _guess_file_mime_type(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix in _SPECIAL_FILE_MIME_TYPES:
        return _SPECIAL_FILE_MIME_TYPES[suffix]
    guessed_mime_type, _encoding = mimetypes.guess_type(file_path.name)
    return guessed_mime_type or "application/octet-stream"
