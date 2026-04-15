from __future__ import annotations

import base64
import json
import mimetypes
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
from save_my_jupyter.parsing import normalize_relative_path_text

_BINARY_FIGURE_MIME_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
}
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


class DocumentArtifactCollector:
    def collect_notebook_artifact(
        self,
        plan: ResolvedSnapshotPlan,
    ) -> NotebookArtifact | None:
        if not plan.effective_config.include_notebook_file:
            return None
        notebook_path = Path(plan.request.notebook_context.notebook_path).resolve()
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
        for output in _iter_notebook_outputs(plan):
            data = _normalize_object_dict(output.get("data"))
            if data is None:
                continue

            figure = _extract_figure_artifact(data, figure_index)
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
            normalized_relative_path = normalize_relative_path_text(
                str(file_path.relative_to(capture_root)).replace("\\", "/")
            )
            relative_path = _make_file_relative_path(
                normalized_relative_path,
                has_repo_root=plan.repo.repo_root is not None,
            )
            file_artifacts[normalized_relative_path] = FileArtifact(
                display_name=file_path.name,
                mime_type=MimeType(_guess_file_mime_type(file_path)),
                local_path=file_path,
                relative_path=relative_path,
            )

        return tuple(file_artifacts[key] for key in sorted(file_artifacts))

    def collect_diff_artifact(self, diff_text: str | None) -> DiffArtifact | None:
        if diff_text is None or diff_text == "":
            return None
        return DiffArtifact(
            display_name="working-tree.patch",
            mime_type=MimeType("text/x-diff"),
            diff_text=diff_text,
        )

    def collect_value_summary(self, plan: ResolvedSnapshotPlan) -> str | None:
        fallback_text: str | None = None
        for output in reversed(tuple(_iter_notebook_outputs(plan))):
            text = _extract_preferred_output_text(output)
            if text is not None:
                return text[:5000]
            if fallback_text is None:
                fallback_text = _extract_output_text(output)
        return fallback_text[:5000] if fallback_text is not None else None

    def collect_all(
        self,
        plan: ResolvedSnapshotPlan,
        diff_text: str | None,
    ) -> tuple[ArtifactRef, ...]:
        artifacts: list[ArtifactRef] = []
        notebook_artifact = self.collect_notebook_artifact(plan)
        if notebook_artifact is not None:
            artifacts.append(notebook_artifact)
        artifacts.extend(self.collect_figure_artifacts(plan))
        artifacts.extend(self.collect_file_artifacts(plan))
        diff_artifact = self.collect_diff_artifact(diff_text)
        if diff_artifact is not None:
            artifacts.append(diff_artifact)
        return tuple(artifacts)


def _extract_figure_artifact(
    data: dict[str, object],
    figure_index: int,
) -> FigureArtifact | None:
    for mime_type, extension in _BINARY_FIGURE_MIME_TYPES.items():
        payload = _normalize_string_payload(data.get(mime_type))
        if payload is None:
            continue
        return FigureArtifact(
            display_name=f"figure-{figure_index:03}.{extension}",
            mime_type=MimeType(mime_type),
            figure_index=figure_index,
            bytes_payload=base64.b64decode(payload),
        )

    for mime_type, extension in _TEXT_FIGURE_MIME_TYPES.items():
        payload = _normalize_string_payload(data.get(mime_type))
        if payload is None:
            continue
        return FigureArtifact(
            display_name=f"figure-{figure_index:03}.{extension}",
            mime_type=MimeType(mime_type),
            figure_index=figure_index,
            bytes_payload=payload.encode("utf-8"),
        )

    return None


def _extract_output_text(output: dict[str, object]) -> str | None:
    text = output.get("text")
    if isinstance(text, str):
        return text
    if "text" in output and isinstance(output["text"], list):
        return "".join(line for line in output["text"] if isinstance(line, str))
    data = _normalize_object_dict(output.get("data"))
    if data is not None:
        text_data = data.get("text/plain")
        if isinstance(text_data, str):
            return text_data
        if isinstance(text_data, list):
            return "".join(line for line in text_data if isinstance(line, str))
    return None


def _extract_preferred_output_text(output: dict[str, object]) -> str | None:
    data = _normalize_object_dict(output.get("data"))
    if data is None:
        return None
    for mime_type in _PREFERRED_SUMMARY_MIME_TYPES:
        text = _normalize_string_payload(data.get(mime_type))
        if text is not None:
            return text
    return None


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
) -> tuple[dict[str, object], ...]:
    notebook_model = _load_notebook_model(plan)
    outputs: list[dict[str, object]] = []
    cells = notebook_model.get("cells")
    if not isinstance(cells, list):
        return ()
    for cell in cells:
        cell_dict = _normalize_object_dict(cell)
        if cell_dict is None:
            continue
        cell_outputs = cell_dict.get("outputs")
        if not isinstance(cell_outputs, list):
            continue
        for output in cell_outputs:
            output_dict = _normalize_object_dict(output)
            if output_dict is not None:
                outputs.append(output_dict)
    return tuple(outputs)


def _resolve_capture_root(plan: ResolvedSnapshotPlan) -> Path:
    if plan.repo.repo_root is not None:
        return Path(plan.repo.repo_root).resolve()
    return Path(plan.request.notebook_context.notebook_path).resolve().parent


def _iter_watched_files(
    plan: ResolvedSnapshotPlan,
    capture_root: Path,
) -> tuple[Path, ...]:
    watched_files: dict[str, Path] = {}
    for watch_path in plan.effective_config.watched_paths:
        absolute_path = capture_root / str(watch_path)
        if absolute_path.is_file():
            watched_files[str(absolute_path.resolve())] = absolute_path.resolve()
            continue
        if absolute_path.is_dir():
            for child in absolute_path.rglob("*"):
                if child.is_file():
                    watched_files[str(child.resolve())] = child.resolve()
    return tuple(watched_files[key] for key in sorted(watched_files))


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
