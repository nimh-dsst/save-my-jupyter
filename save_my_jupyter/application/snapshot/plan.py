"""Pure capture planning (target CAPTURE). Given the effective config and a
kernel-independent notebook outline, decide which artifacts a snapshot will
contain and resolve its tags and run label. No IO: git dirtiness and the
commit decision are passed in by the orchestrator. The result is advisory —
execution recomputes filesystem-dependent matches (contract C-CONFIG-02)."""

from __future__ import annotations

from save_my_jupyter.application.snapshot.directives import merge_tags
from save_my_jupyter.domain.capture import (
    CapturePlan,
    DirectiveResult,
    NotebookOutline,
    PlannedArtifact,
)
from save_my_jupyter.domain.config import EffectiveConfig
from save_my_jupyter.domain.enums import ArtifactKind, SnapshotSource
from save_my_jupyter.domain.provenance import ConfigLayer


def plan_capture(
    *,
    config: EffectiveConfig,
    outline: NotebookOutline,
    source: SnapshotSource,
    directive: DirectiveResult,
    repo_dirty: bool = False,
    will_create_commit: bool = False,
    ui_tags: tuple[str, ...] = (),
    ui_run_label: str | None = None,
    default_tags: tuple[str, ...] = (),
    default_run_label: str | None = None,
    triggering_cell_source: str | None = None,
) -> CapturePlan:
    artifacts: list[PlannedArtifact] = []

    if config.include_notebook_file:
        artifacts.append(
            PlannedArtifact(
                kind=ArtifactKind.NOTEBOOK,
                summary="Notebook (all cells, outputs, metadata)",
            )
        )
    if outline.figure_count > 0 and not config.include_notebook_file:
        suffix = "" if outline.figure_count == 1 else "s"
        artifacts.append(
            PlannedArtifact(
                kind=ArtifactKind.FIGURE,
                summary=f"{outline.figure_count} figure{suffix} from cell outputs",
            )
        )
    for pattern in config.watched_paths:
        artifacts.append(PlannedArtifact(kind=ArtifactKind.FILE, summary=pattern))

    # A separate diff artifact only makes sense when the dirty working tree is not
    # being folded into a fresh commit (contract C-CONTENT-05).
    if config.include_diff_when_dirty and repo_dirty and not will_create_commit:
        artifacts.append(
            PlannedArtifact(
                kind=ArtifactKind.DIFF,
                summary="Working-tree diff (notebook + tracked paths)",
            )
        )

    tags = merge_tags(directive.tags, ui_tags, default_tags)
    run_label, run_label_provenance = _resolve_run_label(
        source=source,
        directive=directive,
        ui_run_label=ui_run_label,
        default_run_label=default_run_label,
        triggering_cell_source=triggering_cell_source,
    )

    return CapturePlan(
        artifacts=tuple(artifacts),
        target=config.target,
        tags=tags,
        run_label=run_label,
        run_label_provenance=run_label_provenance,
    )


def _resolve_run_label(
    *,
    source: SnapshotSource,
    directive: DirectiveResult,
    ui_run_label: str | None,
    default_run_label: str | None,
    triggering_cell_source: str | None,
) -> tuple[str | None, ConfigLayer | None]:
    if ui_run_label is not None and ui_run_label.strip():
        return ui_run_label.strip(), ConfigLayer.REQUEST
    if directive.run_label is not None:
        return directive.run_label, ConfigLayer.NOTEBOOK
    if default_run_label is not None and default_run_label.strip():
        return default_run_label.strip(), ConfigLayer.USER
    if source is SnapshotSource.TRIGGER_CELL and triggering_cell_source is not None:
        label = _first_nonblank_line(triggering_cell_source)
        if label is not None:
            return label, ConfigLayer.INFERRED
    return None, None


def _first_nonblank_line(source: str) -> str | None:
    for line in source.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None
