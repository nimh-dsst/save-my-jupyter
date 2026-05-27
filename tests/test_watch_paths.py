from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from save_my_jupyter.watch_paths import (
    _is_sensitive_file,
    _is_within,
    _passes_safety_gates,
)


@pytest.fixture
def container_root() -> Iterator[Path]:
    root = Path.cwd() / ".test_watch_paths_root"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root.resolve()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_passes_safety_gates_accepts_ordinary_file_inside_container(
    container_root: Path,
) -> None:
    candidate = container_root / "outputs" / "result.csv"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text("value\n1\n", encoding="utf-8")

    assert _passes_safety_gates(candidate.resolve(), container=container_root) is True


def test_passes_safety_gates_rejects_absolute_path_outside_container(
    container_root: Path,
) -> None:
    outside_root = Path.cwd() / ".test_watch_paths_outside"
    shutil.rmtree(outside_root, ignore_errors=True)
    outside_root.mkdir(parents=True, exist_ok=True)
    try:
        outside_file = outside_root / "secret.txt"
        outside_file.write_text("private", encoding="utf-8")

        assert (
            _passes_safety_gates(outside_file.resolve(), container=container_root)
            is False
        )
    finally:
        shutil.rmtree(outside_root, ignore_errors=True)


def test_passes_safety_gates_rejects_sensitive_filename_inside_container(
    container_root: Path,
) -> None:
    env_file = container_root / ".env"
    env_file.write_text("SECRET=1\n", encoding="utf-8")

    assert _passes_safety_gates(env_file.resolve(), container=container_root) is False


def test_passes_safety_gates_rejects_file_in_sensitive_parent_dir(
    container_root: Path,
) -> None:
    ssh_dir = container_root / ".ssh"
    ssh_dir.mkdir()
    key_file = ssh_dir / "config"
    key_file.write_text("Host *", encoding="utf-8")

    assert _passes_safety_gates(key_file.resolve(), container=container_root) is False


def test_is_within_handles_sibling_paths(container_root: Path) -> None:
    sibling = container_root.parent / "unrelated"
    assert _is_within(container_root, container_root) is True
    assert _is_within(sibling, container_root) is False


def test_is_sensitive_file_matches_common_credential_patterns() -> None:
    assert _is_sensitive_file(Path("home/user/.env")) is True
    assert _is_sensitive_file(Path("home/user/.env.local")) is True
    assert _is_sensitive_file(Path("certs/server.pem")) is True
    assert _is_sensitive_file(Path("certs/server.key")) is True
    assert _is_sensitive_file(Path("home/user/id_rsa")) is True
    assert _is_sensitive_file(Path("home/user/id_ed25519")) is True
    assert _is_sensitive_file(Path("home/user/.aws/credentials")) is True
    assert _is_sensitive_file(Path("outputs/result.csv")) is False
    assert _is_sensitive_file(Path("README.md")) is False
