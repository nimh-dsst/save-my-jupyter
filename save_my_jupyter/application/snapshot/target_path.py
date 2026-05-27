"""Pure LabArchives target-path rendering (target DELIVER, contracts
C-TEMPLATE-01/02/03, C-DEST-06). Substitutes the supplied variables into the
template and sanitizes each segment, never escaping the target directory. The
variable catalog is assembled by the orchestrator (it knows the user email,
repo, etc.); a referenced key absent from it is an unknown-variable error."""

from __future__ import annotations

from collections.abc import Mapping

from save_my_jupyter.application.snapshot.guards import sanitize_path_segment
from save_my_jupyter.domain.errors import SnapshotError


def render_target_path(template: str, variables: Mapping[str, str]) -> tuple[str, ...]:
    try:
        rendered = template.format_map(dict(variables))
    except KeyError as exc:
        raise SnapshotError(
            f"Unknown LabArchives target path variable: {exc.args[0]}",
            code="unknown_labarchives_target_path_variable",
            context={"template": template, "variable": str(exc.args[0])},
        ) from exc

    segments: list[str] = []
    for raw_segment in rendered.replace("\\", "/").split("/"):
        sanitized = sanitize_path_segment(raw_segment, template=template)
        if sanitized is not None:
            segments.append(sanitized)

    if not segments:
        raise SnapshotError(
            "LabArchives target path resolved to an empty directory path.",
            code="empty_labarchives_target_path",
            context={"template": template},
        )
    return tuple(segments)
