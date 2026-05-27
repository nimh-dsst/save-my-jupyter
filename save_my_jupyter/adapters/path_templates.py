from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from save_my_jupyter.domain import SnapshotRecord
from save_my_jupyter.errors import LabArchivesWriteError

if TYPE_CHECKING:
    from save_my_jupyter.services.auth import LabArchivesSession

_UNSAFE_PATH_SEGMENT_CODE = "unsafe_labarchives_target_path"
_DRIVE_LETTER_PATTERN = re.compile(r"^[A-Za-z]:$")
_CONTROL_CHARACTERS = frozenset(chr(code) for code in range(32)) | {"\x7f"}


class _TemplateContext(dict[str, str]):
    def __missing__(self, key: str) -> str:
        raise KeyError(key)


def render_root_path_template(
    template: str,
    record: SnapshotRecord,
    session: LabArchivesSession,
) -> tuple[str, ...]:
    try:
        rendered_path = template.format_map(_build_template_context(record, session))
    except KeyError as exc:
        raise LabArchivesWriteError(
            f"Unknown LabArchives target path variable: {exc.args[0]}",
            code="unknown_labarchives_target_path_variable",
            context={"template": template},
        ) from exc

    sanitized_parts: list[str] = []
    for raw_part in rendered_path.replace("\\", "/").split("/"):
        sanitized = _sanitize_segment(raw_part, template=template)
        if sanitized is not None:
            sanitized_parts.append(sanitized)

    if not sanitized_parts:
        raise LabArchivesWriteError(
            "LabArchives target path resolved to an empty directory path.",
            code="empty_labarchives_target_path",
            context={"template": template},
        )
    return tuple(sanitized_parts)


def _sanitize_segment(part: str, *, template: str) -> str | None:
    trimmed = part.strip()
    if trimmed == "..":
        raise LabArchivesWriteError(
            "LabArchives target path segment may not traverse parents.",
            code=_UNSAFE_PATH_SEGMENT_CODE,
            context={"template": template, "segment": part},
        )
    stripped = trimmed.rstrip(".")
    if stripped in {"", "."}:
        return None
    if _DRIVE_LETTER_PATTERN.match(stripped) or ":" in stripped:
        raise LabArchivesWriteError(
            "LabArchives target path segment may not contain a drive letter or colon.",
            code=_UNSAFE_PATH_SEGMENT_CODE,
            context={"template": template, "segment": part},
        )
    if any(character in _CONTROL_CHARACTERS for character in stripped):
        raise LabArchivesWriteError(
            "LabArchives target path segment may not contain control characters.",
            code=_UNSAFE_PATH_SEGMENT_CODE,
            context={"template": template, "segment": part},
        )
    return stripped


def _build_template_context(
    record: SnapshotRecord,
    session: LabArchivesSession,
) -> _TemplateContext:
    timestamp = record.timestamp.isoformat(timespec="seconds").replace(":", "-")
    repo_name = (
        Path(record.repo.repo_root).name
        if record.repo.repo_root is not None
        else "no-repo"
    )
    relative_notebook_path = (
        str(record.repo.relative_notebook_path)
        if record.repo.relative_notebook_path is not None
        else record.notebook_context.notebook_name
    )
    scope_path = relative_notebook_path or record.notebook_context.notebook_name
    return _TemplateContext(
        commit_hash=str(record.commit_hash or "dirty"),
        date=record.timestamp.strftime("%Y-%m-%d"),
        experiment_context=record.metadata.experiment_context or "no-context",
        name=record.labarchives_target.project_name,
        notebook_name=record.notebook_context.notebook_name,
        notebook_stem=Path(record.notebook_context.notebook_name).stem,
        project_name=record.labarchives_target.project_name,
        relative_notebook_path=relative_notebook_path,
        repo_name=repo_name,
        run_label=record.metadata.run_label or "unlabeled",
        scope_name=Path(scope_path).name or scope_path,
        scope_path=scope_path,
        source=record.source.value,
        time=record.timestamp.strftime("%H-%M-%S"),
        timestamp=timestamp,
        user_email=session.user_email or "unknown-email",
        user_id=str(record.user_id),
    )
