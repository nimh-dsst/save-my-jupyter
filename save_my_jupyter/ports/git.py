from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from save_my_jupyter.domain.repo import RepoContext
from save_my_jupyter.domain.types import (
    CommitHash,
    NotebookPath,
    RelativeRepoPath,
    RepoRootPath,
)


class GitInspector(Protocol):
    """Read-only git introspection for a notebook's repository. A read-only
    adapter, not pure: the same call returns different results as the working
    tree changes (contract C-GIT-01)."""

    def resolve_repo(self, notebook_path: NotebookPath) -> RepoContext: ...


class GitMutator(Protocol):
    """Stages snapshot paths and creates the snapshot commit (contract C-GIT).
    Side-effecting, unlike the read-only GitInspector."""

    def stage(
        self, repo_root: RepoRootPath, paths: Sequence[RelativeRepoPath]
    ) -> tuple[RelativeRepoPath, ...]: ...

    def commit(
        self,
        repo_root: RepoRootPath,
        *,
        message: str,
        current_head: CommitHash | None,
    ) -> CommitHash | None: ...
