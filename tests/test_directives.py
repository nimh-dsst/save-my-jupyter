from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from save_my_jupyter.application.snapshot.directives import merge_tags, parse_directives

_FIXTURES: list[dict[str, Any]] = json.loads(
    (Path(__file__).resolve().parent.parent / "fixtures" / "directives.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", _FIXTURES, ids=[case["name"] for case in _FIXTURES])
def test_shared_directive_fixtures(case: dict[str, Any]) -> None:
    # The same fixtures drive ui_tests/directives.test.ts, so the Python and
    # TypeScript parsers cannot drift (contract C-DIRECTIVE-02).
    result = parse_directives(case["cells"])
    assert result.run_label == case["runLabel"]
    assert list(result.tags) == case["tags"]


# --- single directive parsing (C-DIRECTIVE-01) ---


def test_parses_run_and_tags_from_one_directive() -> None:
    result = parse_directives(["# smj: run=training-3; tags=baseline, gpu"])
    assert result.run_label == "training-3"
    assert result.tags == ("baseline", "gpu")


def test_smj_prefix_and_keys_are_case_insensitive_but_values_keep_case() -> None:
    result = parse_directives(["# SMJ: RUN=Training-3; TAGS=Baseline, GPU"])
    assert result.run_label == "Training-3"
    assert result.tags == ("Baseline", "GPU")


def test_recognizes_double_slash_comment_marker() -> None:
    result = parse_directives(["// smj: tags=ts"])
    assert result.tags == ("ts",)


# --- whole-notebook scope and ordering (C-DIRECTIVE-02) ---


def test_tags_union_across_cells_first_run_wins() -> None:
    result = parse_directives(
        [
            "x = 1\n# smj: run=first; tags=a, b",
            "# smj: tags=b, c\n# smj: run=second",
        ]
    )
    assert result.run_label == "first"
    assert result.tags == ("a", "b", "c")


def test_run_only_and_tags_only_directives() -> None:
    run_only = parse_directives(["# smj: run=only-run"])
    assert run_only.run_label == "only-run"
    assert run_only.tags == ()

    tags_only = parse_directives(["# smj: tags=x"])
    assert tags_only.run_label is None
    assert tags_only.tags == ("x",)


# --- non-directive lines are inert (C-DIRECTIVE-01) ---


def test_ignores_non_directive_comments_and_code() -> None:
    result = parse_directives(
        ["# a normal comment", "result = compute()  # smj: tags=trailing"]
    )
    # A trailing inline comment is not a directive line; only full comment lines.
    assert result.run_label is None
    assert result.tags == ()


def test_empty_and_whitespace_tag_values_are_dropped() -> None:
    result = parse_directives(["# smj: tags= , ok ,"])
    assert result.tags == ("ok",)


def test_no_directives_yields_empty_result() -> None:
    result = parse_directives(["import numpy as np", "df.head()"])
    assert result.run_label is None
    assert result.tags == ()


# --- tag merge by union (C-CONTENT-08) ---


def test_merge_tags_union_dedup_and_trim_across_sources() -> None:
    merged = merge_tags(("baseline", "gpu"), ("gpu", " final "), ("baseline",))
    assert merged == ("baseline", "gpu", "final")


def test_merge_tags_drops_blanks() -> None:
    assert merge_tags((" ", ""), ("kept",)) == ("kept",)
