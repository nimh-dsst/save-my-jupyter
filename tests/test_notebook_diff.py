from __future__ import annotations

import base64

from save_my_jupyter.application.snapshot.notebook_diff import render_notebook_diff


def _png_b64(payload: bytes = b"PNG") -> str:
    return base64.b64encode(payload).decode("ascii")


def test_rich_notebook_diff_ignores_execution_noise() -> None:
    before = {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": 1,
                "id": "old-id",
                "metadata": {"collapsed": False},
                "source": "plot()\n",
                "outputs": [
                    {"output_type": "display_data", "data": {"image/png": _png_b64()}}
                ],
            }
        ],
        "metadata": {"kernelspec": {"name": "python"}},
    }
    after = {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": 99,
                "id": "new-id",
                "metadata": {"collapsed": True},
                "source": "plot()\n",
                "outputs": [
                    {
                        "output_type": "display_data",
                        "data": {"image/png": _png_b64(b"DIFFERENT")},
                    }
                ],
            }
        ],
        "metadata": {"language_info": {"name": "python"}},
    }

    assert render_notebook_diff(before, after) is None


def test_rich_notebook_diff_reports_cell_source_changes() -> None:
    before = {"cells": [{"cell_type": "code", "source": "x = 1\n", "outputs": []}]}
    after = {"cells": [{"cell_type": "code", "source": "x = 2\n", "outputs": []}]}

    rendered = render_notebook_diff(before, after)

    assert rendered is not None
    assert rendered.page_name == "01 Notebook Diff"
    assert rendered.summary == "1 of 1 cells changed."
    assert rendered.entries[0].title == "Cell 1 changed (code)"
    assert "Cell 1 changed" in rendered.entries[0].html
    assert "-x = 1" in rendered.entries[0].html
    assert "+x = 2" in rendered.entries[0].html
    assert "--- HEAD" not in rendered.entries[0].html
    assert "+++ snapshot" not in rendered.entries[0].html


def test_rich_notebook_diff_ignores_added_final_empty_cell() -> None:
    before = {"cells": [{"cell_type": "code", "source": "x = 1\n", "outputs": []}]}
    after = {
        "cells": [
            {"cell_type": "code", "source": "x = 1\n", "outputs": []},
            {
                "cell_type": "code",
                "source": " \n",
                "metadata": {"trusted": True},
                "outputs": [],
            },
        ]
    }

    assert render_notebook_diff(before, after) is None


def test_rich_notebook_diff_renders_snapshot_outputs() -> None:
    before = {
        "cells": [{"cell_type": "code", "source": "x\n", "outputs": []}],
    }
    after = {
        "cells": [
            {
                "cell_type": "code",
                "source": "x + 1\n",
                "outputs": [
                    {"output_type": "stream", "name": "stdout", "text": "done\n"},
                    {
                        "output_type": "execute_result",
                        "data": {
                            "text/plain": "42",
                            "image/png": _png_b64(),
                        },
                    },
                ],
            }
        ],
    }

    rendered = render_notebook_diff(before, after)

    assert rendered is not None
    html = rendered.entries[0].html
    assert "Snapshot outputs" in html
    assert "stream (stdout)" in html
    assert "done" in html
    assert "42" in html
    assert "data:image/png;base64" in html
