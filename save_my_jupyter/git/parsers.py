from __future__ import annotations

import re

from save_my_jupyter.domain import CommitHash, RemoteUrl, RepoHost

_COMMIT_HASH_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")


def parse_git_remote(raw: str | None) -> tuple[RepoHost, RemoteUrl | None]:
    if raw is None or raw == "":
        return RepoHost.UNKNOWN, None

    normalized = raw.strip()
    lowered = normalized.lower()
    if "github.com" in lowered:
        return RepoHost.GITHUB, RemoteUrl(normalized)
    if "gitlab" in lowered:
        return RepoHost.GITLAB, RemoteUrl(normalized)
    if "bitbucket" in lowered:
        return RepoHost.BITBUCKET, RemoteUrl(normalized)
    return RepoHost.UNKNOWN, RemoteUrl(normalized)


def parse_commit_hash(raw: str | None) -> CommitHash | None:
    if raw is None:
        return None
    normalized = raw.strip()
    if _COMMIT_HASH_PATTERN.match(normalized) is None:
        return None
    return CommitHash(normalized)
