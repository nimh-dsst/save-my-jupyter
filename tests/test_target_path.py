from __future__ import annotations

import pytest
from save_my_jupyter.application.snapshot.target_path import render_target_path
from save_my_jupyter.domain.errors import SnapshotError

_VARS = {
    "user_email": "a@b.org",
    "project_name": "baseline-study",
    "relative_notebook_path": "analysis/nb.ipynb",
}


# --- substitution (C-TEMPLATE-01, C-DEST-06) ---


def test_renders_default_destination_template() -> None:
    segments = render_target_path(
        "Notebook Log/{user_email}/{project_name}/{relative_notebook_path}", _VARS
    )
    assert segments == (
        "Notebook Log",
        "a@b.org",
        "baseline-study",
        "analysis",
        "nb.ipynb",
    )


def test_backslashes_and_slashes_both_split_segments() -> None:
    segments = render_target_path("a\\b/c", {})
    assert segments == ("a", "b", "c")


# --- unknown / empty (C-TEMPLATE-02) ---


def test_unknown_variable_raises_named_error_before_any_write() -> None:
    with pytest.raises(SnapshotError) as exc:
        render_target_path("Root/{not_a_variable}", _VARS)
    assert exc.value.code == "unknown_labarchives_target_path_variable"
    assert exc.value.context["template"] == "Root/{not_a_variable}"


def test_template_rendering_to_nothing_raises_empty_error() -> None:
    with pytest.raises(SnapshotError) as exc:
        render_target_path("./.", {})
    assert exc.value.code == "empty_labarchives_target_path"


# --- sanitization (C-TEMPLATE-03) ---


def test_parent_traversal_segment_is_unsafe() -> None:
    with pytest.raises(SnapshotError) as exc:
        render_target_path("Root/{seg}", {"seg": ".."})
    assert exc.value.code == "unsafe_labarchives_target_path"
    assert exc.value.context["segment"] == ".."


def test_drive_letter_segment_is_unsafe() -> None:
    with pytest.raises(SnapshotError) as exc:
        render_target_path("{seg}/x", {"seg": "C:"})
    assert exc.value.code == "unsafe_labarchives_target_path"


def test_trailing_dots_stripped_and_dot_segments_dropped() -> None:
    segments = render_target_path("Root/./{seg}/.", {"seg": "baseline."})
    assert segments == ("Root", "baseline")
