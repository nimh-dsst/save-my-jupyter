from __future__ import annotations

from save_my_jupyter.application.config import resolve_effective_config
from save_my_jupyter.domain.config import (
    INFERRED_TARGET_NOTEBOOK,
    INFERRED_TARGET_ROOT_PATH,
    NotebookMetadataConfig,
    RepoConfig,
    UserSettingsConfig,
)
from save_my_jupyter.domain.enums import CommitMode, TriggerMode
from save_my_jupyter.domain.provenance import ConfigLayer
from save_my_jupyter.domain.types import (
    LabArchivesNotebookName,
    LabArchivesRootPath,
    RelativeWatchPath,
)

# --- fresh install: inferred destination + hardcoded fallbacks (C-CONFIG-01/08/11) ---


def test_fresh_install_uses_inferred_destination_and_ask_commit_mode() -> None:
    resolved = resolve_effective_config(
        notebook=NotebookMetadataConfig(), user=UserSettingsConfig(), repo=None
    )
    effective = resolved.effective

    assert effective.commit_mode is CommitMode.ASK
    assert effective.target.notebook_name == INFERRED_TARGET_NOTEBOOK
    assert effective.target.root_path == INFERRED_TARGET_ROOT_PATH
    assert effective.watched_paths == ()
    assert effective.include_notebook_file is True
    assert effective.include_diff_when_dirty is True
    assert effective.all_cells_trigger is False


def test_fresh_install_inferred_root_is_email_scoped_template() -> None:
    # Shared notebooks are the norm, so the default destination is keyed on the
    # authenticated user's email (contract C-DEST-06).
    resolved = resolve_effective_config(
        notebook=NotebookMetadataConfig(), user=UserSettingsConfig(), repo=None
    )
    assert (
        resolved.effective.target.root_path
        == "Notebook Log/{user_email}/{project_name}/{relative_notebook_path}"
    )


def test_fresh_install_provenance_labels_destination_inferred_and_commit_fallback() -> (
    None
):
    resolved = resolve_effective_config(
        notebook=NotebookMetadataConfig(), user=UserSettingsConfig(), repo=None
    )
    assert resolved.provenance["target_notebook"] is ConfigLayer.INFERRED
    assert resolved.provenance["target_root_path"] is ConfigLayer.INFERRED
    assert resolved.provenance["commit_mode"] is ConfigLayer.FALLBACK


# --- commit-mode precedence (C-CONFIG-07, C-GIT-02) ---


def test_request_commit_mode_wins_over_remembered_user_default() -> None:
    resolved = resolve_effective_config(
        request_commit_mode=CommitMode.NEVER,
        notebook=NotebookMetadataConfig(),
        user=UserSettingsConfig(default_commit_mode=CommitMode.ALWAYS),
        repo=RepoConfig(project_name="p", default_commit_mode=CommitMode.PROMPT),
    )
    assert resolved.effective.commit_mode is CommitMode.NEVER
    assert resolved.provenance["commit_mode"] is ConfigLayer.REQUEST


def test_remembered_user_commit_mode_suppresses_ask() -> None:
    resolved = resolve_effective_config(
        notebook=NotebookMetadataConfig(),
        user=UserSettingsConfig(default_commit_mode=CommitMode.ALWAYS),
        repo=None,
    )
    assert resolved.effective.commit_mode is CommitMode.ALWAYS
    assert resolved.provenance["commit_mode"] is ConfigLayer.USER


def test_repo_commit_mode_used_when_user_unset() -> None:
    resolved = resolve_effective_config(
        notebook=NotebookMetadataConfig(),
        user=UserSettingsConfig(),
        repo=RepoConfig(project_name="p", default_commit_mode=CommitMode.NEVER),
    )
    assert resolved.effective.commit_mode is CommitMode.NEVER
    assert resolved.provenance["commit_mode"] is ConfigLayer.REPO


# --- destination precedence (C-CONFIG-01) ---


def test_notebook_target_overrides_repo_and_inferred() -> None:
    resolved = resolve_effective_config(
        notebook=NotebookMetadataConfig(
            labarchives_target_notebook=LabArchivesNotebookName("NB Override"),
            labarchives_target_root_path=LabArchivesRootPath("Custom/Path"),
        ),
        user=UserSettingsConfig(),
        repo=RepoConfig(
            project_name="p",
            default_target_notebook=LabArchivesNotebookName("Repo NB"),
            default_target_root_path=LabArchivesRootPath("Repo/Path"),
        ),
    )
    assert resolved.effective.target.notebook_name == "NB Override"
    assert resolved.effective.target.root_path == "Custom/Path"
    assert resolved.provenance["target_notebook"] is ConfigLayer.NOTEBOOK
    assert resolved.provenance["target_root_path"] is ConfigLayer.NOTEBOOK


def test_repo_target_overrides_inferred() -> None:
    resolved = resolve_effective_config(
        notebook=NotebookMetadataConfig(),
        user=UserSettingsConfig(),
        repo=RepoConfig(
            project_name="p",
            default_target_notebook=LabArchivesNotebookName("Repo NB"),
        ),
    )
    assert resolved.effective.target.notebook_name == "Repo NB"
    assert resolved.provenance["target_notebook"] is ConfigLayer.REPO
    # root falls through to inferred since the repo did not set it
    assert resolved.effective.target.root_path == INFERRED_TARGET_ROOT_PATH
    assert resolved.provenance["target_root_path"] is ConfigLayer.INFERRED


def test_project_name_comes_from_repo_then_fallback() -> None:
    with_repo = resolve_effective_config(
        notebook=NotebookMetadataConfig(),
        user=UserSettingsConfig(),
        repo=RepoConfig(project_name="lab-x"),
    )
    assert with_repo.effective.target.project_name == "lab-x"
    assert with_repo.provenance["project_name"] is ConfigLayer.REPO

    without_repo = resolve_effective_config(
        notebook=NotebookMetadataConfig(), user=UserSettingsConfig(), repo=None
    )
    assert without_repo.effective.target.project_name == "save-my-jupyter"
    assert without_repo.provenance["project_name"] is ConfigLayer.FALLBACK


# --- watched paths (C-CONFIG-08) ---


def test_request_watched_paths_win_over_notebook_and_repo() -> None:
    resolved = resolve_effective_config(
        request_watched_paths=(RelativeWatchPath("request-output"),),
        notebook=NotebookMetadataConfig(watched_paths=(RelativeWatchPath("figures"),)),
        user=UserSettingsConfig(),
        repo=RepoConfig(
            project_name="p",
            default_watch_paths=(RelativeWatchPath("outputs"),),
        ),
    )
    assert resolved.effective.watched_paths == (RelativeWatchPath("request-output"),)
    assert resolved.provenance["watched_paths"] is ConfigLayer.REQUEST


def test_explicit_empty_request_watched_paths_clear_lower_layers() -> None:
    resolved = resolve_effective_config(
        request_watched_paths=(),
        notebook=NotebookMetadataConfig(watched_paths=(RelativeWatchPath("figures"),)),
        user=UserSettingsConfig(),
        repo=RepoConfig(
            project_name="p",
            default_watch_paths=(RelativeWatchPath("outputs"),),
        ),
    )
    assert resolved.effective.watched_paths == ()
    assert resolved.provenance["watched_paths"] is ConfigLayer.REQUEST


def test_empty_notebook_watched_paths_fall_through_to_repo() -> None:
    resolved = resolve_effective_config(
        notebook=NotebookMetadataConfig(watched_paths=()),
        user=UserSettingsConfig(),
        repo=RepoConfig(
            project_name="p",
            default_watch_paths=(RelativeWatchPath("outputs"),),
        ),
    )
    assert resolved.effective.watched_paths == (RelativeWatchPath("outputs"),)
    assert resolved.provenance["watched_paths"] is ConfigLayer.REPO


def test_notebook_watched_paths_win_when_present() -> None:
    resolved = resolve_effective_config(
        notebook=NotebookMetadataConfig(watched_paths=(RelativeWatchPath("figures"),)),
        user=UserSettingsConfig(),
        repo=RepoConfig(
            project_name="p",
            default_watch_paths=(RelativeWatchPath("outputs"),),
        ),
    )
    assert resolved.effective.watched_paths == (RelativeWatchPath("figures"),)
    assert resolved.provenance["watched_paths"] is ConfigLayer.NOTEBOOK


def test_no_watched_paths_anywhere_defaults_empty() -> None:
    resolved = resolve_effective_config(
        notebook=NotebookMetadataConfig(), user=UserSettingsConfig(), repo=None
    )
    assert resolved.effective.watched_paths == ()
    assert resolved.provenance["watched_paths"] is ConfigLayer.FALLBACK


# --- all-cells trigger (C-CONFIG-05) ---


def test_notebook_all_cells_trigger_enables() -> None:
    resolved = resolve_effective_config(
        notebook=NotebookMetadataConfig(trigger_mode=TriggerMode.ALL_CELLS),
        user=UserSettingsConfig(),
        repo=None,
    )
    assert resolved.effective.all_cells_trigger is True
    assert resolved.provenance["all_cells_trigger"] is ConfigLayer.NOTEBOOK


def test_repo_default_all_cells_trigger_enables_when_notebook_marked() -> None:
    resolved = resolve_effective_config(
        notebook=NotebookMetadataConfig(trigger_mode=TriggerMode.MARKED_CELLS),
        user=UserSettingsConfig(),
        repo=RepoConfig(project_name="p", default_all_cells_trigger=True),
    )
    assert resolved.effective.all_cells_trigger is True
    assert resolved.provenance["all_cells_trigger"] is ConfigLayer.REPO


# --- repo-driven content / commit knobs (C-CONFIG-04) ---


def test_repo_overrides_content_and_commit_flags() -> None:
    resolved = resolve_effective_config(
        notebook=NotebookMetadataConfig(),
        user=UserSettingsConfig(),
        repo=RepoConfig(
            project_name="p",
            include_notebook_file=False,
            include_diff_when_dirty=False,
            stage_notebook_on_commit=False,
            stage_watched_paths_on_commit=True,
            commit_message_template="run {notebook_name}",
        ),
    )
    effective = resolved.effective
    assert effective.include_notebook_file is False
    assert effective.include_diff_when_dirty is False
    assert effective.stage_notebook_on_commit is False
    assert effective.stage_watched_paths_on_commit is True
    assert effective.commit_message_template == "run {notebook_name}"
    assert resolved.provenance["include_notebook_file"] is ConfigLayer.REPO
    assert resolved.provenance["commit_message_template"] is ConfigLayer.REPO
