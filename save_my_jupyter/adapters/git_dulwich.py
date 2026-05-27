"""Dulwich-backed read-only git inspection (target CONFIGURE/CAPTURE,
contract C-GIT-01). The only place (with the future mutator) that imports
dulwich. `.ipynb_checkpoints` churn is ignored when judging dirtiness."""

from __future__ import annotations

import re
from collections.abc import Sequence
from fnmatch import fnmatch
from io import BytesIO
from pathlib import Path, PurePosixPath

from dulwich import porcelain
from dulwich.errors import NotGitRepository
from dulwich.object_store import iter_tree_contents
from dulwich.repo import Repo

from save_my_jupyter.domain.errors import SnapshotError
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

    def diff_working_tree(
        self, repo_root: RepoRootPath, paths: Sequence[RelativeRepoPath]
    ) -> str:
        root = Path(repo_root)
        output = BytesIO()
        selected = tuple(str(path).replace("\\", "/") for path in paths)
        try:
            with Repo(str(root)) as repo:
                porcelain.diff(repo, paths=list(selected) or None, outstream=output)
                untracked = [
                    _decode(path)
                    for path in porcelain.status(repo, untracked_files="all").untracked
                ]
        except Exception as exc:
            raise SnapshotError(
                "Unable to generate snapshot diff.",
                code="git_diff_failed",
                context={"error": _describe(exc)},
            ) from exc
        sections = [output.getvalue().decode("utf-8", errors="replace").strip()]
        for path in sorted(untracked):
            normalized = path.replace("\\", "/")
            if selected and not _matches_any_scope(normalized, selected):
                continue
            candidate = root / normalized
            if candidate.is_file():
                sections.append(_added_file_diff(normalized, candidate.read_bytes()))
        return "\n\n".join(section for section in sections if section)

    def read_head_file(
        self, repo_root: RepoRootPath, path: RelativeRepoPath
    ) -> bytes | None:
        try:
            with Repo(str(Path(repo_root))) as repo:
                head = repo[repo.head()]
                for entry in iter_tree_contents(repo.object_store, head.tree):
                    if _decode(entry.path) == str(path):
                        blob = repo.object_store[entry.sha]
                        data = getattr(blob, "data", None)
                        return data if isinstance(data, bytes) else None
        except Exception:
            return None
        return None


class DulwichGitMutator:
    def stage(
        self, repo_root: RepoRootPath, paths: Sequence[RelativeRepoPath]
    ) -> tuple[RelativeRepoPath, ...]:
        if not paths:
            return ()
        root = Path(repo_root)
        absolute = [str(root / path) for path in paths]
        try:
            with Repo(str(root)) as repo:
                _reject_unrelated_staged(repo, paths)
                _added, ignored = porcelain.add(repo, paths=absolute)
        except Exception as exc:
            if isinstance(exc, SnapshotError):
                raise
            raise SnapshotError(
                "Unable to stage snapshot paths.",
                code="git_stage_failed",
                context={"error": _describe(exc)},
            ) from exc
        if ignored:
            raise SnapshotError(
                "Ignored paths cannot be staged.",
                code="git_stage_failed",
                context={"ignored": ", ".join(sorted(ignored))},
            )
        return tuple(paths)

    def commit(
        self,
        repo_root: RepoRootPath,
        *,
        message: str,
        current_head: CommitHash | None,
    ) -> CommitHash | None:
        try:
            with Repo(str(Path(repo_root))) as repo:
                status = porcelain.status(repo, untracked_files="no")
                if not any(status.staged.values()):
                    return current_head
                sha = porcelain.commit(repo, message=message.encode("utf-8"))
        except Exception as exc:
            raise SnapshotError(
                "Unable to create snapshot commit.",
                code="git_commit_failed",
                context={"error": _describe(exc)},
            ) from exc
        parsed = _parse_commit_hash(_decode(sha))
        if parsed is None:
            raise SnapshotError(
                "Commit succeeded but HEAD could not be resolved.",
                code="git_commit_missing_head",
            )
        return parsed


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


def _reject_unrelated_staged(
    repo: Repo, allowed_paths: Sequence[RelativeRepoPath]
) -> None:
    allowed = {str(path).replace("\\", "/") for path in allowed_paths}
    status = porcelain.status(repo, untracked_files="no")
    staged = {_decode(path) for paths in status.staged.values() for path in paths}
    unrelated = sorted(path for path in staged if path not in allowed)
    if unrelated:
        raise SnapshotError(
            "Unrelated staged paths cannot be included in a snapshot commit.",
            code="git_stage_failed",
            context={"staged": ", ".join(unrelated)},
        )


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


def _matches_any_scope(path: str, scopes: Sequence[str]) -> bool:
    return any(_matches_scope(path, scope) for scope in scopes)


def _matches_scope(path: str, scope: str) -> bool:
    normalized_scope = scope.strip("/")
    if not normalized_scope:
        return False
    if any(marker in normalized_scope for marker in "*?["):
        return PurePosixPath(path).match(normalized_scope) or fnmatch(
            path, normalized_scope
        )
    return path == normalized_scope or path.startswith(f"{normalized_scope}/")


def _added_file_diff(path: str, content: bytes) -> str:
    if b"\0" in content:
        return (
            f"diff --git a/{path} b/{path}\n"
            "new file mode 100644\n"
            f"Binary files /dev/null and b/{path} differ"
        )
    text = content.decode("utf-8", errors="replace")
    added = "\n".join(f"+{line}" for line in text.splitlines())
    return (
        f"diff --git a/{path} b/{path}\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        f"+++ b/{path}\n"
        "@@ -0,0 +1 @@\n"
        f"{added}"
    )


def _parse_commit_hash(raw: str) -> CommitHash | None:
    normalized = raw.strip()
    if _COMMIT_HASH_PATTERN.match(normalized) is None:
        return None
    return CommitHash(normalized)


def _describe(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__
