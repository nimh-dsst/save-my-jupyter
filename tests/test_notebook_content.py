from __future__ import annotations

import base64

from save_my_jupyter.application.snapshot.notebook_content import (
    NOTEBOOK_MIME_TYPE,
    extract_figures,
    outline_notebook,
    resolve_artifact_mime_type,
    summarize_execution,
)


def _png_b64() -> str:
    return base64.b64encode(b"PNG-BYTES").decode("ascii")


def _jpg_b64() -> str:
    return base64.b64encode(b"JPG-BYTES").decode("ascii")


def _notebook(cells: list[dict[str, object]]) -> dict[str, object]:
    return {"cells": cells, "nbformat": 4}


def _output(output_type: str, **fields: object) -> dict[str, object]:
    return {"output_type": output_type, **fields}


# --- figures (C-CONTENT-03) ---


def test_figures_numbered_in_order_with_contract_names() -> None:
    notebook = _notebook(
        [
            {"outputs": [_output("display_data", data={"image/png": _png_b64()})]},
            {
                "outputs": [
                    _output("execute_result", data={"text/plain": "42"}),
                    _output("display_data", data={"image/jpeg": _jpg_b64()}),
                ]
            },
            {"outputs": [_output("display_data", data={"image/svg+xml": "<svg/>"})]},
        ]
    )
    figures = extract_figures(notebook)
    assert [fig.name for fig in figures] == [
        "figure-001.png",
        "figure-002.jpg",
        "figure-003.svg",
    ]
    assert figures[0].content == b"PNG-BYTES"
    assert figures[0].mime_type == "image/png"
    assert figures[1].content == b"JPG-BYTES"
    assert figures[2].content == b"<svg/>"
    assert figures[2].mime_type == "image/svg+xml"


def test_text_only_outputs_produce_no_figures() -> None:
    notebook = _notebook(
        [{"outputs": [_output("execute_result", data={"text/plain": "no image"})]}]
    )
    assert extract_figures(notebook) == ()


def test_svg_payload_as_multiline_list_is_joined() -> None:
    notebook = _notebook(
        [{"outputs": [_output("display_data", data={"image/svg+xml": ["<svg", "/>"]})]}]
    )
    figures = extract_figures(notebook)
    assert figures[0].content == b"<svg/>"


# --- execution summary (C-CONTENT-07) ---


def test_summary_is_last_meaningful_output() -> None:
    notebook = _notebook(
        [
            {"outputs": [_output("stream", name="stdout", text="early\n")]},
            {
                "outputs": [
                    _output("execute_result", data={"text/plain": "final value"})
                ]
            },
        ]
    )
    assert summarize_execution(notebook) == "final value"


def test_summary_captures_error_traceback() -> None:
    notebook = _notebook(
        [
            {
                "outputs": [
                    _output(
                        "error",
                        ename="ValueError",
                        evalue="bad",
                        traceback=["Trace line 1\n", "Trace line 2"],
                    )
                ]
            }
        ]
    )
    summary = summarize_execution(notebook)
    assert "ValueError: bad" in summary
    assert "Trace line 1" in summary


def test_summary_truncated_at_5000_chars() -> None:
    notebook = _notebook(
        [{"outputs": [_output("stream", name="stdout", text="x" * 6000)]}]
    )
    assert len(summarize_execution(notebook)) == 5000


def test_summary_fallback_when_no_text_output() -> None:
    notebook = _notebook(
        [{"outputs": [_output("display_data", data={"image/png": _png_b64()})]}]
    )
    assert summarize_execution(notebook) == "(no execution summary available)"


def test_summary_fallback_when_no_outputs() -> None:
    assert summarize_execution(_notebook([])) == "(no execution summary available)"


# --- outline (feeds the planner) ---


def test_outline_counts_cells_figures_and_execution_output() -> None:
    notebook = _notebook(
        [
            {"outputs": [_output("display_data", data={"image/png": _png_b64()})]},
            {"outputs": [_output("execute_result", data={"text/plain": "v"})]},
            {"outputs": []},
        ]
    )
    outline = outline_notebook(notebook)
    assert outline.cell_count == 3
    assert outline.figure_count == 1
    assert outline.has_execution_output is True


def test_outline_no_execution_output() -> None:
    outline = outline_notebook(_notebook([{"outputs": []}, {"source": "x = 1"}]))
    assert outline.figure_count == 0
    assert outline.has_execution_output is False


# --- MIME resolution (C-CONTENT-04) ---


def test_special_extension_mime_types() -> None:
    assert resolve_artifact_mime_type("data.csv") == "text/csv"
    assert resolve_artifact_mime_type("blob.json") == "application/json"
    assert resolve_artifact_mime_type("chart.svg") == "image/svg+xml"
    assert resolve_artifact_mime_type("table.tsv") == "text/tab-separated-values"
    assert resolve_artifact_mime_type("notes.txt") == "text/plain"


def test_unknown_extension_falls_back_to_octet_stream() -> None:
    assert resolve_artifact_mime_type("mystery.zzz") == "application/octet-stream"


def test_notebook_mime_constant() -> None:
    assert NOTEBOOK_MIME_TYPE == "application/x-ipynb+json"
