from __future__ import annotations

import re

from save_my_jupyter.domain import CommitHash, RemoteUrl

_COMMIT_HASH_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")


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
