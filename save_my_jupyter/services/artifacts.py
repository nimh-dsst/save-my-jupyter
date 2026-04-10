from __future__ import annotations

import base64
import json
from pathlib import Path

from save_my_jupyter.domain import (
    ArtifactRef,
    DiffArtifact,
    FigureArtifact,
    FileArtifact,
    MimeType,
    NotebookArtifact,
    RelativeRepoPath,
    ResolvedSnapshotPlan,
)
from save_my_jupyter.errors import ArtifactCollectionError
from save_my_jupyter.parsing import normalize_relative_path_text


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
        notebook_path = Path(plan.request.notebook_context.notebook_path).resolve()
        try:
            notebook_model = json.loads(notebook_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactCollectionError(
                "Unable to read notebook for figure extraction.",
                code="notebook_figure_parse_failed",
                context={"path": str(notebook_path)},
            ) from exc

        figures: list[FigureArtifact] = []
        figure_index = 1
        for cell in notebook_model.get("cells", []):
            if not isinstance(cell, dict):
                continue
            outputs = cell.get("outputs", [])
            if not isinstance(outputs, list):
                continue
            for output in outputs:
                if not isinstance(output, dict):
                    continue
                data = output.get("data")
                if not isinstance(data, dict):
                    continue
                image_data = data.get("image/png")
                if not isinstance(image_data, str):
                    continue
                figures.append(
                    FigureArtifact(
                        display_name=f"figure-{figure_index:03}.png",
                        mime_type=MimeType("image/png"),
                        figure_index=figure_index,
                        bytes_payload=base64.b64decode(image_data),
                    )
                )
                figure_index += 1

        return tuple(figures)

    def collect_file_artifacts(
        self,
        plan: ResolvedSnapshotPlan,
    ) -> tuple[FileArtifact, ...]:
        request = plan.request
        if not hasattr(request, "watched_path_event"):
            return ()

        repo_root = (
            Path(plan.repo.repo_root).resolve()
            if plan.repo.repo_root is not None
            else Path(request.notebook_context.notebook_path).resolve().parent
        )
        changed_path = repo_root / str(request.watched_path_event.relative_path)
        if not changed_path.exists() or not changed_path.is_file():
            return ()

        relative_path = RelativeRepoPath(
            normalize_relative_path_text(
                str(changed_path.relative_to(repo_root)).replace("\\", "/")
            )
        )
        return (
            FileArtifact(
                display_name=changed_path.name,
                mime_type=MimeType("application/octet-stream"),
                local_path=changed_path,
                relative_path=relative_path,
            ),
        )

    def collect_diff_artifact(self, diff_text: str | None) -> DiffArtifact | None:
        if diff_text is None or diff_text == "":
            return None
        return DiffArtifact(
            display_name="working-tree.patch",
            mime_type=MimeType("text/x-diff"),
            diff_text=diff_text,
        )

    def collect_value_summary(self, plan: ResolvedSnapshotPlan) -> str | None:
        notebook_path = Path(plan.request.notebook_context.notebook_path).resolve()
        try:
            notebook_model = json.loads(notebook_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        for cell in reversed(notebook_model.get("cells", [])):
            if not isinstance(cell, dict):
                continue
            outputs = cell.get("outputs")
            if not isinstance(outputs, list):
                continue
            for output in reversed(outputs):
                if not isinstance(output, dict):
                    continue
                text = _extract_output_text(output)
                if text:
                    return text[:5000]
        return None

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


def _extract_output_text(output: dict[str, object]) -> str | None:
    if "text" in output and isinstance(output["text"], list):
        return "".join(line for line in output["text"] if isinstance(line, str))
    data = output.get("data")
    if isinstance(data, dict):
        text_data = data.get("text/plain")
        if isinstance(text_data, str):
            return text_data
        if isinstance(text_data, list):
            return "".join(line for line in text_data if isinstance(line, str))
    return None
