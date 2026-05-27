from __future__ import annotations

from dataclasses import dataclass

from save_my_jupyter.domain.types import (
    CommitHash,
    RelativeRepoPath,
    RemoteUrl,
    RepoRootPath,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RepoContext:
    """The git facts a snapshot needs about the notebook's repository. All
    optional fields are None outside a repo, where ``is_dirty`` is False."""

    repo_root: RepoRootPath | None
    relative_notebook_path: RelativeRepoPath | None
    remote_url: RemoteUrl | None
    head_commit: CommitHash | None
    is_dirty: bool
