from __future__ import annotations

import pytest
from save_my_jupyter.application.config.parse import (
    parse_notebook_metadata,
    parse_repo_config,
    parse_user_settings,
)
from save_my_jupyter.domain.enums import CommitMode, TriggerMode
from save_my_jupyter.domain.errors import SnapshotError

# --- repo config TOML (C-CONFIG-04) ---

_FULL_TOML = """
[project]
name = "lab-x"
repo_root_strategy = "fixed"

[defaults]
all_cells_trigger = true
commit_mode = "always"
watch_paths = ["outputs", "figs/**"]
include_notebook_file = false
include_diff_when_dirty = false

[labarchives]
target_notebook = "Lab NB"
target_root_path = "Runs/{user_email}"

[git]
stage_notebook_on_commit = false
stage_watched_paths_on_commit = true
commit_message_template = "snap {notebook_name}"
"""


def test_full_repo_config_parses_every_section() -> None:
    config = parse_repo_config(_FULL_TOML, default_project_name="fallback")
    assert config.project_name == "lab-x"
    assert config.repo_root_strategy == "fixed"
    assert config.default_all_cells_trigger is True
    assert config.default_commit_mode is CommitMode.ALWAYS
    assert config.default_watch_paths == ("outputs", "figs/**")
    assert config.include_notebook_file is False
    assert config.include_diff_when_dirty is False
    assert config.default_target_notebook == "Lab NB"
    assert config.default_target_root_path == "Runs/{user_email}"
    assert config.stage_notebook_on_commit is False
    assert config.stage_watched_paths_on_commit is True
    assert config.commit_message_template == "snap {notebook_name}"


def test_empty_repo_config_uses_defaults_and_fallback_name() -> None:
    config = parse_repo_config("", default_project_name="fallback")
    assert config.project_name == "fallback"
    assert config.repo_root_strategy == "git"
    assert config.default_all_cells_trigger is None
    assert config.default_commit_mode is None
    assert config.default_watch_paths is None
    assert config.default_target_notebook is None


def test_prompt_commit_mode_is_aliased_to_ask() -> None:
    config = parse_repo_config(
        '[defaults]\ncommit_mode = "prompt"\n', default_project_name="x"
    )
    assert config.default_commit_mode is CommitMode.ASK


def test_invalid_repo_root_strategy_raises() -> None:
    with pytest.raises(SnapshotError) as exc:
        parse_repo_config(
            '[project]\nrepo_root_strategy = "svn"\n', default_project_name="x"
        )
    assert exc.value.code == "invalid_repo_root_strategy"


def test_malformed_toml_raises_parse_failed() -> None:
    with pytest.raises(SnapshotError) as exc:
        parse_repo_config("this is = = not toml", default_project_name="x")
    assert exc.value.code == "repo_config_parse_failed"


# --- notebook metadata (C-CONFIG-05) ---


def test_notebook_metadata_defaults() -> None:
    config = parse_notebook_metadata({})
    assert config.enabled is True
    assert config.trigger_mode is TriggerMode.MARKED_CELLS
    assert config.trigger_cell_ids == frozenset()
    assert config.watched_paths == ()
    assert config.labarchives_target_notebook is None
    assert config.default_metadata == {}


def test_notebook_metadata_parsed() -> None:
    config = parse_notebook_metadata(
        {
            "enabled": True,
            "all_cells_trigger": True,
            "trigger_cell_ids": ["cell-1", "cell-2"],
            "watched_paths": ["outputs"],
            "labarchives_target_notebook": "NB",
            "labarchives_target_root_path": "Root",
            "default_metadata": {"owner": "alice"},
        }
    )
    assert config.trigger_mode is TriggerMode.ALL_CELLS
    assert config.trigger_cell_ids == frozenset({"cell-1", "cell-2"})
    assert config.watched_paths == ("outputs",)
    assert config.labarchives_target_notebook == "NB"
    assert config.default_metadata == {"owner": "alice"}


# --- user settings (C-CONFIG-07) ---


def test_user_settings_defaults_when_empty() -> None:
    config = parse_user_settings({})
    assert config.default_commit_mode is None
    assert config.remember_commit_choice is False
    assert config.default_tags == ()
    assert config.default_run_label is None


def test_user_settings_parsed_and_drops_removed_keys() -> None:
    config = parse_user_settings(
        {
            "defaultCommitMode": "always",
            "rememberCommitChoice": True,
            "defaultTags": ["baseline"],
            "defaultRunLabel": "run-1",
            "defaultExperimentContext": "legacy-removed-value",
        }
    )
    assert config.default_commit_mode is CommitMode.ALWAYS
    assert config.remember_commit_choice is True
    assert config.default_tags == ("baseline",)
    assert config.default_run_label == "run-1"
