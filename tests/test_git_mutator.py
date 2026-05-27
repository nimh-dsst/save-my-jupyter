from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from dulwich import porcelain
from dulwich.repo import Repo
from save_my_jupyter.adapters.git_dulwich import DulwichGitMutator
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.domain.types import CommitHash, RelativeRepoPath, RepoRootPath

if TYPE_CHECKING:
    from save_my_jupyter.ports import GitMutator

_AUTHOR = b"Test <test@example.org>"


def _init_repo(tmp_path: Path) -> None:
    porcelain.init(str(tmp_path))
    with Repo(str(tmp_path)) as repo:
        config = repo.get_config()
        config.set((b"user",), b"name", b"Test")
        config.set((b"user",), b"email", b"test@example.org")
        config.write_to_path()


def _initial_commit(tmp_path: Path, name: str, content: bytes) -> CommitHash:
    (tmp_path / name).write_bytes(content)
    porcelain.add(str(tmp_path), paths=[str(tmp_path / name)])
    sha = porcelain.commit(
        str(tmp_path), message=b"init", author=_AUTHOR, committer=_AUTHOR
    )
    return CommitHash(sha.decode("ascii"))


def test_stage_and_commit_after_change_creates_new_commit(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    initial = _initial_commit(tmp_path, "nb.ipynb", b"{}")
    (tmp_path / "nb.ipynb").write_bytes(b'{"x": 1}')

    mutator: GitMutator = DulwichGitMutator()
    root = RepoRootPath(str(tmp_path))
    staged = mutator.stage(root, [RelativeRepoPath("nb.ipynb")])
    assert staged == (RelativeRepoPath("nb.ipynb"),)

    new_head = mutator.commit(root, message="snapshot", current_head=initial)
    assert new_head is not None
    assert new_head != initial
    assert len(new_head) == 40


def test_commit_with_no_changes_reuses_existing_head(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    initial = _initial_commit(tmp_path, "nb.ipynb", b"{}")

    mutator = DulwichGitMutator()
    root = RepoRootPath(str(tmp_path))
    mutator.stage(root, [RelativeRepoPath("nb.ipynb")])  # nothing changed
    result = mutator.commit(root, message="snapshot", current_head=initial)
    assert result == initial


def test_staging_nothing_returns_empty(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _initial_commit(tmp_path, "nb.ipynb", b"{}")
    assert DulwichGitMutator().stage(RepoRootPath(str(tmp_path)), []) == ()


def test_staging_outside_a_repo_fails_with_git_stage_failed(tmp_path: Path) -> None:
    # tmp_path is not a git repository, so opening it raises and is wrapped.
    (tmp_path / "f.csv").write_bytes(b"x")
    with pytest.raises(SnapshotError) as exc:
        DulwichGitMutator().stage(
            RepoRootPath(str(tmp_path)), [RelativeRepoPath("f.csv")]
        )
    assert exc.value.code == "git_stage_failed"
