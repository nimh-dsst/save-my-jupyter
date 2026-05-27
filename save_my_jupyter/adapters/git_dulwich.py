"""Dulwich-backed read-only git inspection (target CONFIGURE/CAPTURE,
contract C-GIT-01). The only place (with the future mutator) that imports
dulwich. `.ipynb_checkpoints` churn is ignored when judging dirtiness."""

from __future__ import annotations

import re
from pathlib import Path

from dulwich import porcelain
from dulwich.errors import NotGitRepository
from dulwich.repo import Repo

from save_my_jupyter.domain.repo import RepoContext
from save_my_jupyter.domain.types import (
    CommitHash,
    NotebookPath,
    RelativeRepoPath,
    RemoteUrl,
    RepoRootPath,
)

_COMMIT_HASH_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")
_IGNORED_PATH_PARTS = frozenset({".ipynb_checkpoints"})

_NO_REPO = RepoContext(
    repo_root=None,
    relative_notebook_path=None,
    remote_url=None,
    head_commit=None,
    is_dirty=False,
)


class DulwichGitInspector:
    def resolve_repo(self, notebook_path: NotebookPath) -> RepoContext:
        notebook = Path(notebook_path).resolve()
        try:
            with Repo.discover(str(notebook.parent)) as repo:
                repo_root = Path(repo.path).resolve()
                remote_url = _remote_url(repo)
                head_commit = _head_commit(repo)
                is_dirty = _is_dirty(repo)
        except NotGitRepository:
            return _NO_REPO

        try:
            relative: RelativeRepoPath | None = RelativeRepoPath(
                notebook.relative_to(repo_root).as_posix()
            )
        except ValueError:
            relative = None
        return RepoContext(
            repo_root=RepoRootPath(str(repo_root)),
            relative_notebook_path=relative,
            remote_url=remote_url,
            head_commit=head_commit,
            is_dirty=is_dirty,
        )


def _head_commit(repo: Repo) -> CommitHash | None:
    try:
        head = repo.head()
    except KeyError:
        return None
    return _parse_commit_hash(_decode(head))


def _is_dirty(repo: Repo) -> bool:
    status = _status(repo)
    staged = [path for paths in status.staged.values() for path in paths]
    candidates = [*staged, *status.unstaged, *status.untracked]
    return any(not _is_ignored(_decode(path)) for path in candidates)


def _status(repo: Repo):
    try:
        return porcelain.status(repo, untracked_files="all")
    except OSError:
        return porcelain.status(repo, untracked_files="no")


def _remote_url(repo: Repo) -> RemoteUrl | None:
    config = repo.get_config()
    try:
        raw = config.get((b"remote", b"origin"), b"url")
    except KeyError:
        return None
    text = _decode(raw)
    return RemoteUrl(text) if text else None


def _decode(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="surrogateescape")
    return str(value)


def _is_ignored(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return any(part in _IGNORED_PATH_PARTS for part in parts)


def _parse_commit_hash(raw: str) -> CommitHash | None:
    normalized = raw.strip()
    if _COMMIT_HASH_PATTERN.match(normalized) is None:
        return None
    return CommitHash(normalized)
