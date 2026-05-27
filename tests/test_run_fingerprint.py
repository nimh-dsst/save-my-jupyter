from __future__ import annotations

from save_my_jupyter.application.snapshot.fingerprint import compute_run_fingerprint


def _fingerprint(**overrides: object) -> str:
    base: dict[str, object] = {
        "notebook_key": "doc-1",
        "document_id": "doc-1",
        "kernel_id": "kernel-1",
        "triggered_cell_ids": ("cell-a", "cell-b"),
        "execution_count": 5,
    }
    base.update(overrides)
    return compute_run_fingerprint(**base)  # type: ignore[arg-type]


def test_identical_runs_share_a_fingerprint() -> None:
    assert _fingerprint() == _fingerprint()


def test_triggered_cell_order_does_not_matter() -> None:
    assert _fingerprint(triggered_cell_ids=("cell-a", "cell-b")) == _fingerprint(
        triggered_cell_ids=("cell-b", "cell-a")
    )


def test_tag_set_is_part_of_fingerprint() -> None:
    assert _fingerprint(tags=("baseline",)) != _fingerprint(tags=("baseline", "qc"))


def test_tag_order_and_blank_padding_do_not_matter() -> None:
    assert _fingerprint(tags=("qc", " baseline ", "")) == _fingerprint(
        tags=("baseline", "qc")
    )


def test_different_triggered_cells_differ() -> None:
    assert _fingerprint(triggered_cell_ids=("cell-a",)) != _fingerprint(
        triggered_cell_ids=("cell-a", "cell-b")
    )


def test_different_execution_count_differs() -> None:
    assert _fingerprint(execution_count=5) != _fingerprint(execution_count=6)


def test_different_kernel_differs() -> None:
    assert _fingerprint(kernel_id="kernel-1") != _fingerprint(kernel_id="kernel-2")


def test_fingerprint_is_hex_digest() -> None:
    value = _fingerprint()
    assert len(value) == 64
    assert all(character in "0123456789abcdef" for character in value)
