from __future__ import annotations

from dataclasses import dataclass

from save_my_jupyter.domain.config import LabArchivesTarget
from save_my_jupyter.domain.enums import ArtifactKind
from save_my_jupyter.domain.provenance import ConfigLayer


@dataclass(frozen=True, slots=True, kw_only=True)
class DirectiveResult:
    """Tags and run label declared in notebook source via `# smj:` directives
    (contracts C-DIRECTIVE-01/02). ``tags`` is de-duplicated in first-seen order;
    ``run_label`` is the first ``run=`` directive in notebook order, or None."""

    run_label: str | None
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class NotebookOutline:
    """Kernel-independent summary of a notebook's structure, sufficient to plan
    what a snapshot will contain without reading the full notebook again."""

    cell_count: int
    figure_count: int
    has_execution_output: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class PlannedArtifact:
    """One line in the 'What will be saved' preview."""

    kind: ArtifactKind
    summary: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CapturePlan:
    """The advisory plan the panel shows before a snapshot runs (contract
    C-CONFIG-02). Execution recomputes filesystem-dependent matches, so this is
    a point-in-time projection, not the authoritative receipt."""

    artifacts: tuple[PlannedArtifact, ...]
    target: LabArchivesTarget
    tags: tuple[str, ...]
    run_label: str | None
    run_label_provenance: ConfigLayer | None = None
