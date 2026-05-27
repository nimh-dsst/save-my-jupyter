from __future__ import annotations

import difflib
import re
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from dulwich import porcelain
from dulwich.errors import NotGitRepository
from dulwich.objects import Blob
from dulwich.repo import Repo

from save_my_jupyter.config.service import ConfigService
from save_my_jupyter.domain import (
    CommitHash,
    RelativeRepoPath,
    RemoteUrl,
    RepoRootPath,
    ResolvedRepoContext,
    ResolvedSnapshotPlan,
)
from save_my_jupyter.errors import CommitCreationError, GitResolutionError
from save_my_jupyter.parsing import normalize_path
from save_my_jupyter.watch_paths import resolve_watch_targets

_COMMIT_HASH_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")
_IGNORED_PATH_PARTS = frozenset({".ipynb_checkpoints"})


class DefaultGitService:
    def resolve_repo(self, notebook_path: str) -> ResolvedRepoContext:
        notebook = Path(notebook_path).resolve()
        try:
            with Repo.discover(notebook.parent) as repo:
                repo_root = Path(repo.path).resolve()
                remote_url = parse_git_remote(self._remote_url(repo))
                head_commit = self._head_commit(repo)
                is_dirty = self._is_dirty(repo)
        except NotGitRepository:
            return ResolvedRepoContext(
                repo_root=None,
                relative_notebook_path=None,
                remote_url=None,
                head_commit=None,
                is_dirty=False,
            )

        relative_notebook_path = RelativeRepoPath(
            normalize_path(str(notebook.relative_to(repo_root)).replace("\\", "/"))
        )
        return ResolvedRepoContext(
            repo_root=RepoRootPath(str(repo_root)),
            relative_notebook_path=relative_notebook_path,
            remote_url=remote_url,
            head_commit=head_commit,
            is_dirty=is_dirty,
        )

    def stage_snapshot_paths(self, plan: ResolvedSnapshotPlan) -> list[str]:
        if plan.repo.repo_root is None:
            return []

        repo_root = Path(plan.repo.repo_root)
        try:
            with Repo(str(repo_root)) as repo:
                paths = self._stage_targets(plan, repo_root, repo)
                if not paths:
                    return []
                _added_paths, ignored_paths = porcelain.add(repo, paths=paths)
        except Exception as exc:
            raise CommitCreationError(
                "Unable to stage snapshot paths.",
                code="git_stage_failed",
                context={"stderr": self._error_message(exc)},
            ) from exc

        if ignored_paths:
            raise CommitCreationError(
                "Unable to stage snapshot paths.",
                code="git_stage_failed",
                context={
                    "stderr": (
                        "Ignored paths cannot be staged: "
                        + ", ".join(sorted(ignored_paths))
                    )
                },
            )
        return paths

    def create_commit(self, plan: ResolvedSnapshotPlan) -> CommitHash | None:
        if plan.repo.repo_root is None:
            return None

        repo_root = Path(plan.repo.repo_root)
        target_paths = self.stage_snapshot_paths(plan)

        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        message = plan.effective_config.commit_message_template.format(
            notebook_name=plan.request.notebook_context.notebook_name,
            timestamp=timestamp,
        )
        try:
            with Repo(str(repo_root)) as repo:
                if not self._has_staged_changes(repo, target_paths):
                    return plan.repo.head_commit
                commit_bytes = porcelain.commit(repo, message=message)
        except Exception as exc:
            raise CommitCreationError(
                "Unable to create snapshot commit.",
                code="git_commit_failed",
                context={"stderr": self._error_message(exc)},
            ) from exc

        commit_hash = parse_commit_hash(commit_bytes.decode("ascii"))
        if commit_hash is None:
            raise CommitCreationError(
                "Commit succeeded but HEAD could not be resolved.",
                code="git_commit_missing_head",
            )
        return commit_hash

    def generate_diff(self, plan: ResolvedSnapshotPlan) -> str | None:
        if plan.repo.repo_root is None:
            return None

        repo_root = Path(plan.repo.repo_root)
        diff_targets = self._diff_targets(plan, repo_root)
        if not diff_targets:
            return None
        outstream = BytesIO()
        untracked_diff = ""
        try:
            with Repo(str(repo_root)) as repo:
                if self._head_commit(repo) is None:
                    return self._diff_without_head(
                        repo_root=repo_root,
                        diff_targets=diff_targets,
                    )
                porcelain.diff(
                    repo,
                    commit=b"HEAD",
                    paths=diff_targets,
                    outstream=outstream,
                )
                untracked_diff = self._untracked_diff(
                    repo,
                    repo_root=repo_root,
                    diff_targets=diff_targets,
                )
        except Exception as exc:
            if isinstance(exc, GitResolutionError):
                raise
            raise GitResolutionError(
                "Unable to generate git diff.",
                code="git_diff_failed",
                context={"stderr": self._error_message(exc)},
            ) from exc

        tracked_diff = outstream.getvalue().decode("utf-8").strip()
        diff_sections = [
            section for section in (tracked_diff, untracked_diff) if section != ""
        ]
        return "\n\n".join(diff_sections) or None

    def _diff_without_head(
        self,
        *,
        repo_root: Path,
        diff_targets: list[str],
    ) -> str:
        sections: list[str] = []
        for relative_path in diff_targets:
            if _is_ignored_repo_path(relative_path):
                continue
            absolute_path = (repo_root / relative_path).resolve()
            if not absolute_path.is_file():
                continue
            sections.append(_render_added_file_diff(absolute_path, relative_path))
        return "\n\n".join(sections)

    def build_commit_url(
        self,
        remote_url: str | None,
        commit_hash: CommitHash | None,
    ) -> str | None:
        if remote_url is None or commit_hash is None:
            return None

        normalized_remote = remote_url.removesuffix(".git")
        if normalized_remote.startswith("git@"):
            normalized_remote = normalized_remote.replace("git@", "https://")
            normalized_remote = normalized_remote.replace(":", "/", 1)
        if "github.com" in normalized_remote:
            return f"{normalized_remote}/commit/{commit_hash}"
        if "gitlab" in normalized_remote:
            return f"{normalized_remote}/-/commit/{commit_hash}"
        if "bitbucket" in normalized_remote:
            return f"{normalized_remote}/commits/{commit_hash}"
        return None

    def _stage_targets(
        self,
        plan: ResolvedSnapshotPlan,
        repo_root: Path,
        repo: Repo,
    ) -> list[str]:
        targets: list[str] = []
        if plan.effective_config.stage_notebook_on_commit:
            targets.append(
                self._relative_repo_path(
                    repo_root,
                    Path(plan.request.notebook_context.notebook_path).resolve(),
                )
            )
        if plan.effective_config.stage_watched_paths_on_commit:
            targets.extend(
                resolve_watch_targets(
                    repo_root=repo_root,
                    watch_paths=plan.effective_config.watched_paths,
                )
            )
        repo_config_target = self._repo_config_target(
            plan,
            repo_root=repo_root,
            repo=repo,
        )
        if repo_config_target is not None:
            targets.append(repo_config_target)
        return sorted(dict.fromkeys(targets))

    def _diff_targets(
        self,
        plan: ResolvedSnapshotPlan,
        repo_root: Path,
    ) -> list[str]:
        targets = [
            self._relative_repo_path(
                repo_root,
                Path(plan.request.notebook_context.notebook_path).resolve(),
            )
        ]
        targets.extend(
            resolve_watch_targets(
                repo_root=repo_root,
                watch_paths=plan.effective_config.watched_paths,
            )
        )
        return sorted(dict.fromkeys(targets))

    def _has_staged_changes(self, repo: Repo, target_paths: list[str]) -> bool:
        if not target_paths:
            return False
        status = porcelain.status(repo, untracked_files="no")
        staged_paths = {
            _normalize_repo_path(path)
            for paths in status.staged.values()
            for path in paths
        }
        return bool(staged_paths & set(target_paths))

    def _untracked_diff(
        self,
        repo: Repo,
        *,
        repo_root: Path,
        diff_targets: list[str],
    ) -> str:
        status = self._status_with_fallback(repo)
        untracked_targets = {
            normalized_path
            for path in status.untracked
            if not _is_ignored_repo_path(normalized_path := _normalize_repo_path(path))
        }
        sections: list[str] = []
        for relative_path in diff_targets:
            if relative_path not in untracked_targets:
                continue
            absolute_path = (repo_root / relative_path).resolve()
            if not absolute_path.is_file():
                continue
            sections.append(_render_added_file_diff(absolute_path, relative_path))
        return "\n\n".join(sections)

    def _head_commit(self, repo: Repo) -> CommitHash | None:
        try:
            return parse_commit_hash(repo.head().decode("ascii"))
        except KeyError:
            return None

    def _is_dirty(self, repo: Repo) -> bool:
        status = self._status_with_fallback(repo)
        staged_paths = {
            normalized_path
            for paths in status.staged.values()
            for path in paths
            if not _is_ignored_repo_path(normalized_path := _normalize_repo_path(path))
        }
        unstaged_paths = {
            normalized_path
            for path in status.unstaged
            if not _is_ignored_repo_path(normalized_path := _normalize_repo_path(path))
        }
        untracked_paths = {
            normalized_path
            for path in status.untracked
            if not _is_ignored_repo_path(normalized_path := _normalize_repo_path(path))
        }
        return bool(staged_paths or unstaged_paths or untracked_paths)

    def _status_with_fallback(self, repo: Repo) -> porcelain.GitStatus:
        try:
            return porcelain.status(repo, untracked_files="all")
        except OSError:
            return porcelain.status(repo, untracked_files="no")

    def _remote_url(self, repo: Repo) -> str | None:
        config = repo.get_config()
        try:
            raw_remote = config.get((b"remote", b"origin"), b"url")
        except KeyError:
            return None
        return self._decode_text(raw_remote)

    def _relative_repo_path(self, repo_root: Path, path: Path) -> str:
        return normalize_path(str(path.relative_to(repo_root)).replace("\\", "/"))

    def _repo_config_target(
        self,
        plan: ResolvedSnapshotPlan,
        *,
        repo_root: Path,
        repo: Repo,
    ) -> str | None:
        config_path = ConfigService().suggested_repo_config_path(
            notebook_path=plan.request.notebook_context.notebook_path,
            repo_root=repo_root,
        )
        try:
            relative_path = self._relative_repo_path(repo_root, config_path.resolve())
        except ValueError:
            return None

        status = self._status_with_fallback(repo)
        touched_paths = {
            _normalize_repo_path(path)
            for paths in status.staged.values()
            for path in paths
        }
        touched_paths.update(_normalize_repo_path(path) for path in status.unstaged)
        touched_paths.update(_normalize_repo_path(path) for path in status.untracked)
        if relative_path in touched_paths:
            return relative_path

        try:
            repo.open_index().get_mode(relative_path.encode("utf-8"))
        except KeyError:
            return None
        return relative_path

    def _decode_text(self, value: object) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="surrogateescape")
        return str(value)

    def _error_message(self, exc: Exception) -> str:
        message = str(exc).strip()
        return message or exc.__class__.__name__


def parse_git_remote(raw: str | None) -> RemoteUrl | None:
    if raw is None or raw == "":
        return None

    normalized = raw.strip()
    return RemoteUrl(normalized)


def parse_commit_hash(raw: str | None) -> CommitHash | None:
    if raw is None:
        return None
    normalized = raw.strip()
    if _COMMIT_HASH_PATTERN.match(normalized) is None:
        return None
    return CommitHash(normalized)


def _normalize_repo_path(path: bytes | str) -> str:
    if isinstance(path, bytes):
        decoded = path.decode("utf-8", errors="surrogateescape")
    else:
        decoded = path
    return normalize_path(decoded.replace("\\", "/"))


def _is_ignored_repo_path(path: str) -> bool:
    normalized = normalize_path(path.replace("\\", "/"))
    return any(part in _IGNORED_PATH_PARTS for part in normalized.split("/"))


def _render_added_file_diff(path: Path, relative_path: str) -> str:
    payload = path.read_bytes()
    blob_hash = Blob.from_string(payload).id.decode("ascii")[:7]
    header = [
        f"diff --git a/{relative_path} b/{relative_path}",
        f"new file mode {_git_file_mode(path)}",
        f"index 0000000..{blob_hash}",
    ]
    body = _render_added_file_body(payload, relative_path)
    return "\n".join([*header, body]).strip()


def _render_added_file_body(payload: bytes, relative_path: str) -> str:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return f"Binary files /dev/null and b/{relative_path} differ"
    if "\x00" in text:
        return f"Binary files /dev/null and b/{relative_path} differ"

    lines = text.splitlines()
    rendered = "\n".join(
        difflib.unified_diff(
            [],
            lines,
            fromfile="/dev/null",
            tofile=f"b/{relative_path}",
            lineterm="",
        )
    )
    if rendered != "":
        return rendered
    return "\n".join(
        [
            "--- /dev/null",
            f"+++ b/{relative_path}",
        ]
    )


def _git_file_mode(path: Path) -> str:
    return "100755" if path.stat().st_mode & 0o111 else "100644"
