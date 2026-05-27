from __future__ import annotations

from save_my_jupyter.application.snapshot.diff import (
    DIFF_FILTER_QUALIFIER,
    filter_diff,
)

_NOTEBOOK_SECTION = (
    "diff --git a/analysis/nb.ipynb b/analysis/nb.ipynb\n"
    "--- a/analysis/nb.ipynb\n+++ b/analysis/nb.ipynb\n@@ -1 +1 @@\n-{}\n+{x}"
)
_IMAGE_SECTION = (
    "diff --git a/figs/plot.png b/figs/plot.png\n"
    "Binary files a/figs/plot.png and b/figs/plot.png differ"
)
_CODE_SECTION = (
    "diff --git a/src/train.py b/src/train.py\n"
    "--- a/src/train.py\n+++ b/src/train.py\n@@ -1 +1 @@\n-x = 1\n+x = 2"
)


def test_drops_notebook_and_image_sections_keeps_code() -> None:
    diff_text = "\n\n".join([_NOTEBOOK_SECTION, _IMAGE_SECTION, _CODE_SECTION])
    filtered = filter_diff(diff_text, notebook_relative_path="analysis/nb.ipynb")
    assert filtered is not None
    assert "src/train.py" in filtered
    assert "nb.ipynb" not in filtered
    assert "plot.png" not in filtered


def test_returns_none_when_only_notebook_and_images_remain() -> None:
    diff_text = "\n\n".join([_NOTEBOOK_SECTION, _IMAGE_SECTION])
    assert filter_diff(diff_text, notebook_relative_path="analysis/nb.ipynb") is None


def test_blank_diff_returns_none() -> None:
    assert filter_diff("", notebook_relative_path=None) is None


def test_truncates_oversized_diff() -> None:
    big_body = "+" + "x" * 2_000_000
    section = (
        f"diff --git a/data.txt b/data.txt\n--- a/data.txt\n+++ b/data.txt\n{big_body}"
    )
    filtered = filter_diff(section, notebook_relative_path=None)
    assert filtered is not None
    assert len(filtered) < 1_100_000
    assert "truncated" in filtered.lower()


def test_qualifier_constant_matches_contract() -> None:
    assert DIFF_FILTER_QUALIFIER == (
        "Filtered working tree patch; notebook JSON and image patches are omitted"
    )
