from __future__ import annotations

from pathlib import Path

from save_my_jupyter.domain import SnapshotRecord
from save_my_jupyter.errors import LabArchivesWriteError


class _TemplateContext(dict[str, str]):
    def __missing__(self, key: str) -> str:
        raise KeyError(key)


def render_root_path_template(template: str, record: SnapshotRecord) -> tuple[str, ...]:
    try:
        rendered_path = template.format_map(_build_template_context(record))
    except KeyError as exc:
        raise LabArchivesWriteError(
            f"Unknown LabArchives target path variable: {exc.args[0]}",
            code="unknown_labarchives_target_path_variable",
            context={"template": template},
        ) from exc

    parts = tuple(
        part.strip()
        for part in rendered_path.replace("\\", "/").split("/")
        if part.strip() != ""
    )
    if not parts:
        raise LabArchivesWriteError(
            "LabArchives target path resolved to an empty directory path.",
            code="empty_labarchives_target_path",
            context={"template": template},
        )
    return parts


def _build_template_context(record: SnapshotRecord) -> _TemplateContext:
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
    scope_path = (
        record.path_rule_name
        or relative_notebook_path
        or record.notebook_context.notebook_name
    )
    return _TemplateContext(
        commit_hash=str(record.commit_hash or "dirty"),
        date=record.timestamp.strftime("%Y-%m-%d"),
        experiment_context=record.metadata.experiment_context or "no-context",
        notebook_name=record.notebook_context.notebook_name,
        notebook_stem=Path(record.notebook_context.notebook_name).stem,
        path_rule_name=record.path_rule_name or "unscoped",
        relative_notebook_path=relative_notebook_path,
        repo_name=repo_name,
        run_label=record.metadata.run_label or "unlabeled",
        scope_name=Path(scope_path).name or scope_path,
        scope_path=scope_path,
        source=record.source.value,
        time=record.timestamp.strftime("%H-%M-%S"),
        timestamp=timestamp,
        user_id=str(record.user_id),
    )
