from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from dulwich import porcelain
from dulwich.repo import Repo
from save_my_jupyter.adapters.git_dulwich import DulwichGitInspector
from save_my_jupyter.domain.types import NotebookPath

if TYPE_CHECKING:
    from save_my_jupyter.domain.repo import RepoContext
    from save_my_jupyter.ports import GitInspector

_AUTHOR = b"Test <test@example.org>"


def _commit_file(repo_path: Path, relative: str, content: bytes) -> None:
    target = repo_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    porcelain.add(str(repo_path), paths=[str(target)])
    porcelain.commit(
        str(repo_path), message=b"commit", author=_AUTHOR, committer=_AUTHOR
    )


def _resolve(repo_path: Path, relative: str) -> RepoContext:
    inspector: GitInspector = DulwichGitInspector()
    return inspector.resolve_repo(NotebookPath(str(repo_path / relative)))


def test_outside_a_repo_reports_no_repo(tmp_path: Path) -> None:
    context = _resolve(tmp_path, "nb.ipynb")
    assert context.repo_root is None
    assert context.relative_notebook_path is None
    assert context.head_commit is None
    assert context.is_dirty is False


def test_clean_repo_resolves_root_relative_path_and_head(tmp_path: Path) -> None:
    porcelain.init(str(tmp_path))
    _commit_file(tmp_path, "analysis/nb.ipynb", b"{}")

    context = _resolve(tmp_path, "analysis/nb.ipynb")
    assert context.repo_root is not None
    assert Path(context.repo_root) == tmp_path.resolve()
    assert context.relative_notebook_path == "analysis/nb.ipynb"
    assert context.head_commit is not None
    assert len(context.head_commit) == 40
    assert context.is_dirty is False


def test_uncommitted_change_makes_repo_dirty(tmp_path: Path) -> None:
    porcelain.init(str(tmp_path))
    _commit_file(tmp_path, "nb.ipynb", b"{}")
    (tmp_path / "extra.txt").write_text("untracked")

    assert _resolve(tmp_path, "nb.ipynb").is_dirty is True


def test_ipynb_checkpoints_do_not_count_as_dirty(tmp_path: Path) -> None:
    porcelain.init(str(tmp_path))
    _commit_file(tmp_path, "nb.ipynb", b"{}")
    checkpoint = tmp_path / ".ipynb_checkpoints" / "nb-checkpoint.ipynb"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text("{}")

    assert _resolve(tmp_path, "nb.ipynb").is_dirty is False


def test_remote_origin_url_is_resolved(tmp_path: Path) -> None:
    porcelain.init(str(tmp_path))
    _commit_file(tmp_path, "nb.ipynb", b"{}")
    with Repo(str(tmp_path)) as repo:
        config = repo.get_config()
        config.set((b"remote", b"origin"), b"url", b"git@github.com:example/repo.git")
        config.write_to_path()

    context = _resolve(tmp_path, "nb.ipynb")
    assert context.remote_url == "git@github.com:example/repo.git"
