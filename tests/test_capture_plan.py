from __future__ import annotations

from save_my_jupyter.application.snapshot.plan import plan_capture
from save_my_jupyter.domain.capture import CapturePlan, DirectiveResult, NotebookOutline
from save_my_jupyter.domain.config import EffectiveConfig, LabArchivesTarget
from save_my_jupyter.domain.enums import ArtifactKind, CommitMode, SnapshotSource
from save_my_jupyter.domain.types import (
    LabArchivesNotebookName,
    LabArchivesRootPath,
    RelativeWatchPath,
)


def _config(**overrides: object) -> EffectiveConfig:
    base: dict[str, object] = {
        "all_cells_trigger": False,
        "commit_mode": CommitMode.ASK,
        "watched_paths": (),
        "include_notebook_file": True,
        "include_diff_when_dirty": True,
        "target": LabArchivesTarget(
            notebook_name=LabArchivesNotebookName("Jupyter Snapshots"),
            root_path=LabArchivesRootPath("Notebook Log/{user_email}"),
        ),
        "metadata_template": {},
        "stage_notebook_on_commit": True,
        "stage_watched_paths_on_commit": False,
        "commit_message_template": "snapshot: {notebook_name} {timestamp}",
    }
    base.update(overrides)
    return EffectiveConfig(**base)  # type: ignore[arg-type]


_NO_DIRECTIVE = DirectiveResult(run_label=None, tags=())
_OUTLINE = NotebookOutline(cell_count=4, figure_count=0, has_execution_output=True)


def _kinds(plan: CapturePlan) -> list[ArtifactKind]:
    return [artifact.kind for artifact in plan.artifacts]


# --- notebook inclusion (C-CONTENT-01) ---


def test_notebook_artifact_included_by_default() -> None:
    plan = plan_capture(
        config=_config(),
        outline=_OUTLINE,
        source=SnapshotSource.MANUAL,
        directive=_NO_DIRECTIVE,
    )
    assert ArtifactKind.NOTEBOOK in _kinds(plan)


def test_notebook_artifact_excluded_when_disabled() -> None:
    plan = plan_capture(
        config=_config(include_notebook_file=False),
        outline=_OUTLINE,
        source=SnapshotSource.MANUAL,
        directive=_NO_DIRECTIVE,
    )
    assert ArtifactKind.NOTEBOOK not in _kinds(plan)


# --- figures (C-CONTENT-03) ---


def test_figure_artifact_present_only_when_outputs_have_images() -> None:
    with_figs = plan_capture(
        config=_config(),
        outline=NotebookOutline(
            cell_count=2, figure_count=3, has_execution_output=True
        ),
        source=SnapshotSource.MANUAL,
        directive=_NO_DIRECTIVE,
    )
    assert ArtifactKind.FIGURE in _kinds(with_figs)

    without = plan_capture(
        config=_config(),
        outline=_OUTLINE,
        source=SnapshotSource.MANUAL,
        directive=_NO_DIRECTIVE,
    )
    assert ArtifactKind.FIGURE not in _kinds(without)


# --- watched paths (C-CONTENT-04) ---


def test_watched_paths_become_file_artifacts() -> None:
    plan = plan_capture(
        config=_config(
            watched_paths=(RelativeWatchPath("outputs"), RelativeWatchPath("figs/**"))
        ),
        outline=_OUTLINE,
        source=SnapshotSource.MANUAL,
        directive=_NO_DIRECTIVE,
    )
    file_summaries = [a.summary for a in plan.artifacts if a.kind is ArtifactKind.FILE]
    assert file_summaries == ["outputs", "figs/**"]


# --- diff (C-CONTENT-05) ---


def test_diff_included_when_dirty_and_not_committing() -> None:
    plan = plan_capture(
        config=_config(),
        outline=_OUTLINE,
        source=SnapshotSource.MANUAL,
        directive=_NO_DIRECTIVE,
        repo_dirty=True,
        will_create_commit=False,
    )
    assert ArtifactKind.DIFF in _kinds(plan)


def test_diff_excluded_when_committing() -> None:
    plan = plan_capture(
        config=_config(),
        outline=_OUTLINE,
        source=SnapshotSource.MANUAL,
        directive=_NO_DIRECTIVE,
        repo_dirty=True,
        will_create_commit=True,
    )
    assert ArtifactKind.DIFF not in _kinds(plan)


def test_diff_excluded_when_clean_or_disabled() -> None:
    clean = plan_capture(
        config=_config(),
        outline=_OUTLINE,
        source=SnapshotSource.MANUAL,
        directive=_NO_DIRECTIVE,
        repo_dirty=False,
    )
    assert ArtifactKind.DIFF not in _kinds(clean)

    disabled = plan_capture(
        config=_config(include_diff_when_dirty=False),
        outline=_OUTLINE,
        source=SnapshotSource.MANUAL,
        directive=_NO_DIRECTIVE,
        repo_dirty=True,
    )
    assert ArtifactKind.DIFF not in _kinds(disabled)


# --- tags merge (C-CONTENT-08) ---


def test_tags_merge_directive_ui_and_defaults() -> None:
    plan = plan_capture(
        config=_config(),
        outline=_OUTLINE,
        source=SnapshotSource.MANUAL,
        directive=DirectiveResult(run_label=None, tags=("baseline", "gpu")),
        ui_tags=("gpu", "manual"),
        default_tags=("baseline", "lab"),
    )
    assert plan.tags == ("baseline", "gpu", "manual", "lab")


# --- run label timing (C-DIRECTIVE-02/03) ---


def test_ui_run_label_wins() -> None:
    plan = plan_capture(
        config=_config(),
        outline=_OUTLINE,
        source=SnapshotSource.MANUAL,
        directive=DirectiveResult(run_label="from-directive", tags=()),
        ui_run_label="from-ui",
    )
    assert plan.run_label == "from-ui"


def test_directive_run_label_used_when_no_ui() -> None:
    plan = plan_capture(
        config=_config(),
        outline=_OUTLINE,
        source=SnapshotSource.MANUAL,
        directive=DirectiveResult(run_label="from-directive", tags=()),
    )
    assert plan.run_label == "from-directive"


def test_trigger_falls_back_to_first_nonblank_line() -> None:
    plan = plan_capture(
        config=_config(),
        outline=_OUTLINE,
        source=SnapshotSource.TRIGGER_CELL,
        directive=_NO_DIRECTIVE,
        triggering_cell_source="\n\n  train(model)  \n# rest",
    )
    assert plan.run_label == "train(model)"


def test_manual_without_directive_or_ui_has_no_run_label() -> None:
    plan = plan_capture(
        config=_config(),
        outline=_OUTLINE,
        source=SnapshotSource.MANUAL,
        directive=_NO_DIRECTIVE,
        triggering_cell_source="ignored for manual",
    )
    assert plan.run_label is None


def test_target_is_passed_through() -> None:
    plan = plan_capture(
        config=_config(),
        outline=_OUTLINE,
        source=SnapshotSource.MANUAL,
        directive=_NO_DIRECTIVE,
    )
    assert plan.target.notebook_name == "Jupyter Snapshots"
