from __future__ import annotations

import base64

from save_my_jupyter.application.snapshot.notebook_render import render_notebook_html
from save_my_jupyter.domain.delivery import NotebookDiff, NotebookDiffEntry


def _png_b64(payload: bytes = b"PNG") -> str:
    return base64.b64encode(payload).decode("ascii")


def test_notebook_html_renders_cells_outputs_and_images() -> None:
    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "source": "# Results\n\nReady",
            },
            {
                "cell_type": "code",
                "source": "plot()\n",
                "outputs": [
                    {"output_type": "stream", "name": "stdout", "text": "started\n"},
                    {
                        "output_type": "execute_result",
                        "data": {
                            "text/plain": "42",
                            "image/png": _png_b64(),
                        },
                    },
                    {
                        "output_type": "error",
                        "ename": "ValueError",
                        "evalue": "bad value",
                        "traceback": ["Traceback line\n"],
                    },
                ],
            },
        ],
    }

    html = render_notebook_html("nb.ipynb", notebook)

    assert "Notebook nb.ipynb" in html
    assert "Cell 1 (markdown)" in html
    assert "# Results" in html
    assert "Cell 2 (code)" in html
    assert "plot()" in html
    assert "stream (stdout)" in html
    assert "started" in html
    assert "execute result" in html
    assert "42" in html
    assert "data:image/png;base64" in html
    assert "ValueError: bad value" in html


def test_notebook_html_syntax_highlights_code_cells() -> None:
    notebook = {
        "metadata": {"language_info": {"name": "python"}},
        "cells": [
            {
                "cell_type": "code",
                "source": 'value = "hello"\nprint(value)\n',
                "outputs": [],
            }
        ],
    }

    html = render_notebook_html("nb.ipynb", notebook)

    assert '<span style="' in html
    assert "value" in html
    assert "print" in html


def test_notebook_html_uses_diff_view_when_diff_is_available() -> None:
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "source": "x = 2\n",
                "outputs": [],
            }
        ],
    }
    notebook_diff = NotebookDiff(
        page_name="01 Notebook Diff",
        summary="1 of 1 cells changed.",
        entries=(
            NotebookDiffEntry(
                title="Cell 1 changed",
                html="<section><h3>Cell 1 changed</h3><pre>+x = 2</pre></section>",
            ),
        ),
    )

    html = render_notebook_html("nb.ipynb", notebook, notebook_diff=notebook_diff)

    assert "Notebook nb.ipynb" in html
    assert "Notebook diff" in html
    assert "1 of 1 cells changed." in html
    assert "Cell 1 changed" in html
    assert "+x = 2" in html
    assert "Cell 1 (code)" not in html


def test_notebook_html_escapes_user_content() -> None:
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "source": "<script>alert(1)</script>",
                "outputs": [
                    {
                        "output_type": "display_data",
                        "data": {"text/html": "<b>unsafe</b>"},
                    }
                ],
            }
        ]
    }

    html = render_notebook_html("nb.ipynb", notebook)

    assert "<script>" not in html
    assert "&lt;" in html
    assert "&gt;" in html
    assert "<b>unsafe</b>" not in html
    assert "&lt;b&gt;unsafe&lt;/b&gt;" not in html


def test_notebook_html_omits_raw_html_table_outputs() -> None:
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "source": "df\n",
                "outputs": [
                    {
                        "output_type": "execute_result",
                        "data": {
                            "text/plain": "   value\n0      1",
                            "text/html": (
                                "<table><tr><th>value</th></tr>"
                                "<tr><td>1</td></tr></table>"
                            ),
                        },
                    }
                ],
            }
        ]
    }

    html = render_notebook_html("nb.ipynb", notebook)

    assert "   value" in html
    assert "HTML output:" not in html
    assert "<table>" not in html
    assert "&lt;table&gt;" not in html
