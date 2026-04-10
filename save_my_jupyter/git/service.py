from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from save_my_jupyter.domain import (
    CommitHash,
    RelativeRepoPath,
    RepoHost,
    RepoRootPath,
    ResolvedRepoContext,
    ResolvedSnapshotPlan,
)
from save_my_jupyter.errors import CommitCreationError, GitResolutionError
from save_my_jupyter.git.parsers import parse_commit_hash, parse_git_remote
from save_my_jupyter.parsing import normalize_relative_path_text


@dataclass(frozen=True, slots=True)
class GitCommandResult:
    stdout: str
    stderr: str
    returncode: int


class DefaultGitService:
    def resolve_repo(self, notebook_path: str) -> ResolvedRepoContext:
        notebook = Path(notebook_path).resolve()
        repo_root_output = self._run_git(
            notebook.parent, "rev-parse", "--show-toplevel"
        )
        if repo_root_output.returncode != 0:
            return ResolvedRepoContext(
                repo_root=None,
                relative_notebook_path=None,
                remote_url=None,
                repo_host=RepoHost.UNKNOWN,
                head_commit=None,
                is_dirty=False,
            )

        repo_root = Path(repo_root_output.stdout.strip())
        remote_result = self._run_git(repo_root, "config", "--get", "remote.origin.url")
        host, remote_url = parse_git_remote(
            remote_result.stdout.strip() if remote_result.returncode == 0 else None
        )
        head_result = self._run_git(repo_root, "rev-parse", "HEAD")
        dirty_result = self._run_git(repo_root, "status", "--porcelain")
        relative_notebook_path = RelativeRepoPath(
            normalize_relative_path_text(
                str(notebook.relative_to(repo_root)).replace("\\", "/")
            )
        )
        return ResolvedRepoContext(
            repo_root=RepoRootPath(str(repo_root)),
            relative_notebook_path=relative_notebook_path,
            remote_url=remote_url,
            repo_host=host,
            head_commit=parse_commit_hash(
                head_result.stdout.strip() if head_result.returncode == 0 else None
            ),
            is_dirty=dirty_result.stdout.strip() != "",
        )

    def stage_snapshot_paths(self, plan: ResolvedSnapshotPlan) -> None:
        if plan.repo.repo_root is None:
            return

        repo_root = Path(plan.repo.repo_root)
        paths: list[str] = []
        if plan.effective_config.stage_notebook_on_commit:
            paths.append(
                str(Path(plan.request.notebook_context.notebook_path).resolve())
            )
        if plan.effective_config.stage_watched_paths_on_commit:
            for watch_path in plan.effective_config.watched_paths:
                paths.append(str(repo_root / str(watch_path)))

        if not paths:
            return

        result = self._run_git(repo_root, "add", "--", *paths)
        if result.returncode != 0:
            raise CommitCreationError(
                "Unable to stage snapshot paths.",
                code="git_stage_failed",
                context={"stderr": result.stderr.strip()},
            )

    def create_commit(self, plan: ResolvedSnapshotPlan) -> CommitHash | None:
        if plan.repo.repo_root is None:
            return None

        repo_root = Path(plan.repo.repo_root)
        self.stage_snapshot_paths(plan)

        if not self._has_staged_changes(repo_root):
            return plan.repo.head_commit

        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        message = plan.effective_config.commit_message_template.format(
            notebook_name=plan.request.notebook_context.notebook_name,
            timestamp=timestamp,
        )
        commit_result = self._run_git(repo_root, "commit", "-m", message)
        if commit_result.returncode != 0:
            raise CommitCreationError(
                "Unable to create snapshot commit.",
                code="git_commit_failed",
                context={"stderr": commit_result.stderr.strip()},
            )

        head_result = self._run_git(repo_root, "rev-parse", "HEAD")
        commit_hash = parse_commit_hash(head_result.stdout.strip())
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
        diff_targets = self._diff_targets(plan)
        diff_result = self._run_git(repo_root, "diff", "HEAD", "--", *diff_targets)
        if diff_result.returncode != 0:
            raise GitResolutionError(
                "Unable to generate git diff.",
                code="git_diff_failed",
                context={"stderr": diff_result.stderr.strip()},
            )
        diff_text = diff_result.stdout.strip()
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

    def _diff_targets(self, plan: ResolvedSnapshotPlan) -> list[str]:
        targets = [str(plan.request.notebook_context.notebook_path)]
        targets.extend(
            str(watch_path) for watch_path in plan.effective_config.watched_paths
        )
        return targets

    def _has_staged_changes(self, repo_root: Path) -> bool:
        result = self._run_git(repo_root, "diff", "--cached", "--name-only")
        return result.stdout.strip() != ""

    def _run_git(self, cwd: Path, *args: str) -> GitCommandResult:
        completed = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            check=False,
            text=True,
        )
        return GitCommandResult(
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
        )
