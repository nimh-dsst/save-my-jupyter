"""Pure run fingerprint (target TRIGGER, contracts C-QUEUE-02/08). Keyed on the
run, not an individual cell: the triggered-cell set is order-insensitive, so a
Run All that fires several trigger cells hashes to one fingerprint regardless of
cell ordering. User-entered tags are part of the fingerprint so a researcher can
add tags after a run and submit a new snapshot without changing executable code.
Manual snapshots never dedupe, so the queue ignores their fingerprint rather
than this function special-casing them."""

from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256

from save_my_jupyter.domain.types import RunFingerprint


def compute_run_fingerprint(
    *,
    notebook_key: str,
    document_id: str | None,
    kernel_id: str | None,
    triggered_cell_ids: Sequence[str],
    execution_count: int | None,
    tags: Sequence[str] = (),
) -> RunFingerprint:
    material = "|".join(
        [
            notebook_key,
            document_id or "",
            kernel_id or "",
            ",".join(sorted(triggered_cell_ids)),
            str(execution_count) if execution_count is not None else "",
            ",".join(_normalized_tags(tags)),
        ]
    )
    return RunFingerprint(sha256(material.encode("utf-8")).hexdigest())


def _normalized_tags(tags: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({tag.strip() for tag in tags if tag.strip()}))
