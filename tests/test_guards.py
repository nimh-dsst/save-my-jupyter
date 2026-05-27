from __future__ import annotations

import sys
from pathlib import PurePosixPath, PureWindowsPath

import pytest
from save_my_jupyter.application.snapshot import guards as guards_module
from save_my_jupyter.application.snapshot.guards import (
    NOTEBOOK_MAX_BYTES,
    WATCHED_FILE_MAX_BYTES,
    enforce_size_cap,
    is_ignored_path,
    is_sensitive_file,
    is_within_root,
    matches_watch_pattern,
    sanitize_path_segment,
    validate_watched_path,
)
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.domain.guards import WatchedPathAccepted, WatchedPathRejected

# --- watched-path validation (C-WATCH-02) ---


def test_validate_rejects_empty() -> None:
    result = validate_watched_path("   ")
    assert isinstance(result, WatchedPathRejected)
    assert result.message == "Watched paths must not be empty."
    assert result.code == "invalid_sequence_item"


@pytest.mark.parametrize("raw", ["/abs/path", "\\\\server\\share", "C:\\x"])
def test_validate_rejects_absolute(raw: str) -> None:
    result = validate_watched_path(raw)
    assert isinstance(result, WatchedPathRejected)
    assert result.message == "Watched paths must be relative."
    assert result.code == "absolute_path_not_allowed"


def test_validate_rejects_parent_traversal() -> None:
    result = validate_watched_path("outputs/../secrets")
    assert isinstance(result, WatchedPathRejected)
    assert result.message == "Watched paths must stay within the notebook or repo root."
    assert result.code == "path_escapes_root"


def test_validate_rejects_dot_only() -> None:
    result = validate_watched_path("./././")
    assert isinstance(result, WatchedPathRejected)
    assert result.message == "Watched paths must include at least one path segment."
    assert result.code == "invalid_sequence_item"


def test_validate_normalizes_to_posix() -> None:
    result = validate_watched_path("outputs\\nested\\.\\result.csv")
    assert result == WatchedPathAccepted(normalized="outputs/nested/result.csv")


# --- containment (C-WATCH-05) ---


def test_is_within_root() -> None:
    root = PurePosixPath("/repo")
    assert is_within_root(PurePosixPath("/repo/sub/a.csv"), root)
    assert is_within_root(root, root)
    assert not is_within_root(PurePosixPath("/elsewhere/a.csv"), root)


# --- sensitive / ignored (C-WATCH-06, C-WATCH-07) ---


@pytest.mark.parametrize(
    "path",
    [
        "repo/.env",
        "repo/.env.local",
        "repo/certs/server.pem",
        "repo/keys/server.key",
        "repo/id_rsa",
        "repo/id_ed25519.pub",
        "repo/.netrc",
        "home/.ssh/config",
        "home/.aws/credentials",
        "repo/creds/credentials.json",
    ],
)
def test_is_sensitive_file_true(path: str) -> None:
    assert is_sensitive_file(PurePosixPath(path))


@pytest.mark.parametrize("path", ["repo/outputs/result.csv", "repo/README.md"])
def test_is_sensitive_file_false(path: str) -> None:
    assert not is_sensitive_file(PurePosixPath(path))


@pytest.mark.parametrize(
    "path",
    [
        "repo/__pycache__/m.pyc",
        "repo/.git/config",
        "repo/node_modules/x/index.js",
        "repo/.venv/lib/x.py",
        "repo/.ipynb_checkpoints/nb-checkpoint.ipynb",
    ],
)
def test_is_ignored_path_true(path: str) -> None:
    assert is_ignored_path(PurePosixPath(path))


def test_is_ignored_path_false() -> None:
    assert not is_ignored_path(PurePosixPath("repo/src/module.py"))


def test_sensitive_match_case_sensitivity_matches_platform() -> None:
    # Case folding applies on Windows only; the assertion follows the platform.
    upper = PureWindowsPath("repo/.ENV")
    if sys.platform == "win32":
        assert is_sensitive_file(upper)
    else:
        assert not is_sensitive_file(upper)


def test_sensitive_parent_dirs_are_case_insensitive_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(guards_module, "_FILENAMES_ARE_CASE_INSENSITIVE", True)

    assert is_sensitive_file(PureWindowsPath("repo/.SSH/config"))
    assert is_sensitive_file(PureWindowsPath("repo/.AWS/Credentials"))


def test_sensitive_parent_dirs_are_case_sensitive_on_posix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(guards_module, "_FILENAMES_ARE_CASE_INSENSITIVE", False)

    assert not is_sensitive_file(PurePosixPath("repo/.SSH/config"))
    assert is_sensitive_file(PurePosixPath("repo/.AWS/credentials"))


# --- watch pattern matching (C-WATCH-03) ---


def test_matches_watch_pattern() -> None:
    assert matches_watch_pattern(candidate="a/b/c.py", pattern="**/*.py")
    assert matches_watch_pattern(candidate="top.py", pattern="**/*.py")
    assert matches_watch_pattern(candidate="outputs/x.csv", pattern="outputs")
    assert not matches_watch_pattern(candidate="other/x.csv", pattern="outputs")
    assert not matches_watch_pattern(candidate="a/b/c.txt", pattern="**/*.py")


# --- size caps (C-CONTENT-01, C-WATCH-08) ---


def test_enforce_size_cap_under_limit_ok() -> None:
    enforce_size_cap(
        size_bytes=10,
        max_bytes=WATCHED_FILE_MAX_BYTES,
        code="watched_file_artifact_too_large",
        path=PurePosixPath("x.csv"),
    )


def test_enforce_size_cap_over_limit_raises() -> None:
    with pytest.raises(SnapshotError) as exc:
        enforce_size_cap(
            size_bytes=NOTEBOOK_MAX_BYTES + 1,
            max_bytes=NOTEBOOK_MAX_BYTES,
            code="notebook_artifact_too_large",
            path=PurePosixPath("big.ipynb"),
        )
    assert exc.value.code == "notebook_artifact_too_large"
    assert exc.value.context["path"] == "big.ipynb"


# --- path-template sanitization (C-TEMPLATE-03) ---


def test_sanitize_rejects_parent() -> None:
    with pytest.raises(SnapshotError) as exc:
        sanitize_path_segment("..", template="Notebook Log/{run_label}")
    assert exc.value.code == "unsafe_labarchives_target_path"
    assert exc.value.context["segment"] == ".."


def test_sanitize_rejects_drive_letter_and_colon() -> None:
    for bad in ("C:", "a:b"):
        with pytest.raises(SnapshotError):
            sanitize_path_segment(bad, template="t")


def test_sanitize_drops_dot_and_empty() -> None:
    assert sanitize_path_segment(".", template="t") is None
    assert sanitize_path_segment("   ", template="t") is None


def test_sanitize_strips_trailing_dots() -> None:
    assert sanitize_path_segment("baseline.", template="t") == "baseline"


def test_sanitize_keeps_normal_segment() -> None:
    assert sanitize_path_segment("user@example.com", template="t") == "user@example.com"
