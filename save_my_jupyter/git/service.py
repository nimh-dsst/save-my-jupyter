from __future__ import annotations

import re
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from dulwich import porcelain
from dulwich.errors import NotGitRepository
from dulwich.repo import Repo

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

_COMMIT_HASH_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")


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

    def stage_snapshot_paths(self, plan: ResolvedSnapshotPlan) -> None:
        if plan.repo.repo_root is None:
            return

        repo_root = Path(plan.repo.repo_root)
        paths = self._stage_targets(plan, repo_root)
        if not paths:
            return

        try:
            with Repo(str(repo_root)) as repo:
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

    def create_commit(self, plan: ResolvedSnapshotPlan) -> CommitHash | None:
        if plan.repo.repo_root is None:
            return None

        repo_root = Path(plan.repo.repo_root)
        self.stage_snapshot_paths(plan)

        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        message = plan.effective_config.commit_message_template.format(
            notebook_name=plan.request.notebook_context.notebook_name,
            timestamp=timestamp,
        )
        try:
            with Repo(str(repo_root)) as repo:
                if not self._has_staged_changes(repo):
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
        outstream = BytesIO()
        try:
            with Repo(str(repo_root)) as repo:
                if self._head_commit(repo) is None:
                    raise GitResolutionError(
                        "Unable to generate git diff.",
                        code="git_diff_failed",
                        context={
                            "stderr": ("HEAD is not available for diff generation.")
                        },
                    )
                porcelain.diff(
                    repo,
                    commit=b"HEAD",
                    paths=diff_targets,
                    outstream=outstream,
                )
        except Exception as exc:
            if isinstance(exc, GitResolutionError):
                raise
            raise GitResolutionError(
                "Unable to generate git diff.",
                code="git_diff_failed",
                context={"stderr": self._error_message(exc)},
            ) from exc

        diff_text = outstream.getvalue().decode("utf-8").strip()
        return diff_text or None

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
                normalize_path(str(watch_path))
                for watch_path in plan.effective_config.watched_paths
            )
        return targets

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
            normalize_path(str(watch_path))
            for watch_path in plan.effective_config.watched_paths
        )
        return targets

    def _has_staged_changes(self, repo: Repo) -> bool:
        status = porcelain.status(repo, untracked_files="no")
        return any(status.staged.values())

    def _head_commit(self, repo: Repo) -> CommitHash | None:
        try:
            return parse_commit_hash(repo.head().decode("ascii"))
        except KeyError:
            return None

    def _is_dirty(self, repo: Repo) -> bool:
        try:
            status = porcelain.status(repo, untracked_files="all")
        except OSError:
            status = porcelain.status(repo, untracked_files="no")
        return bool(status.unstaged or status.untracked or any(status.staged.values()))

    def _remote_url(self, repo: Repo) -> str | None:
        config = repo.get_config()
        try:
            raw_remote = config.get((b"remote", b"origin"), b"url")
        except KeyError:
            return None
        return self._decode_text(raw_remote)

    def _relative_repo_path(self, repo_root: Path, path: Path) -> str:
        return normalize_path(str(path.relative_to(repo_root)).replace("\\", "/"))

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
