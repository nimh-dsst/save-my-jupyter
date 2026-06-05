from __future__ import annotations

import os

from save_my_jupyter.env import load_server_dotenv


def test_load_server_dotenv_reads_server_root_env_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ACCESS_KEYID", raising=False)
    monkeypatch.delenv("ACCESS_PWD", raising=False)
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "ACCESS_KEYID=dotenv-key\nACCESS_PWD=dotenv-secret\n",
        encoding="utf-8",
    )

    loaded = load_server_dotenv(tmp_path)

    assert loaded == dotenv_path
    assert os.environ["ACCESS_KEYID"] == "dotenv-key"
    assert os.environ["ACCESS_PWD"] == "dotenv-secret"


def test_load_server_dotenv_does_not_override_process_environment(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("ACCESS_KEYID", "process-key")
    monkeypatch.delenv("ACCESS_PWD", raising=False)
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "ACCESS_KEYID=dotenv-key\nACCESS_PWD=dotenv-secret\n",
        encoding="utf-8",
    )

    load_server_dotenv(tmp_path)

    assert os.environ["ACCESS_KEYID"] == "process-key"
    assert os.environ["ACCESS_PWD"] == "dotenv-secret"


def test_load_server_dotenv_ignores_missing_file(tmp_path) -> None:
    assert load_server_dotenv(tmp_path) is None
