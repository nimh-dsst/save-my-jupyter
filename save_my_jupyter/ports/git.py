from __future__ import annotations

from typing import Protocol

from save_my_jupyter.domain.repo import RepoContext
from save_my_jupyter.domain.types import NotebookPath


class GitInspector(Protocol):
    """Read-only git introspection for a notebook's repository. A read-only
    adapter, not pure: the same call returns different results as the working
    tree changes (contract C-GIT-01)."""

    def resolve_repo(self, notebook_path: NotebookPath) -> RepoContext: ...
