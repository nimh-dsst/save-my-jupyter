from __future__ import annotations

from save_my_jupyter.application.snapshot.commit_url import build_commit_url

_HASH = "abcdef1234567890"


def test_github_ssh_remote() -> None:
    assert (
        build_commit_url("git@github.com:org/repo.git", _HASH)
        == f"https://github.com/org/repo/commit/{_HASH}"
    )


def test_github_https_remote() -> None:
    assert (
        build_commit_url("https://github.com/org/repo.git", _HASH)
        == f"https://github.com/org/repo/commit/{_HASH}"
    )


def test_gitlab_remote_uses_dash_commit() -> None:
    assert (
        build_commit_url("git@gitlab.com:org/repo.git", _HASH)
        == f"https://gitlab.com/org/repo/-/commit/{_HASH}"
    )


def test_bitbucket_remote_uses_commits() -> None:
    assert (
        build_commit_url("https://bitbucket.org/org/repo.git", _HASH)
        == f"https://bitbucket.org/org/repo/commits/{_HASH}"
    )


def test_unknown_host_has_no_url() -> None:
    assert build_commit_url("git@example.com:org/repo.git", _HASH) is None


def test_missing_remote_or_hash_has_no_url() -> None:
    assert build_commit_url(None, _HASH) is None
    assert build_commit_url("git@github.com:org/repo.git", None) is None
