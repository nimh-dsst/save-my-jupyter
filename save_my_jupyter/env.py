"""Server-process environment loading."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


def load_server_dotenv(root_dir: Path) -> Path | None:
    dotenv_path = root_dir / ".env"
    if not dotenv_path.is_file():
        return None
    load_dotenv(dotenv_path=dotenv_path, override=False)
    return dotenv_path
