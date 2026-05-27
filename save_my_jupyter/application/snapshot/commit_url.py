"""Pure commit-URL construction (target DELIVER, contract C-DEST-05). Turns a
git remote and commit hash into a clickable web URL for GitHub/GitLab/Bitbucket;
returns None for unknown hosts or missing inputs (no IO)."""

from __future__ import annotations

from save_my_jupyter.domain.types import RemoteUrl


def build_commit_url(
    remote_url: str | None, commit_hash: str | None
) -> RemoteUrl | None:
    if remote_url is None or commit_hash is None:
        return None

    normalized = remote_url.removesuffix(".git")
    if normalized.startswith("git@"):
        # git@host:org/repo -> https://host/org/repo (swap the host:path colon
        # before adding the scheme, so https:// is not itself mangled).
        normalized = "https://" + normalized.removeprefix("git@").replace(":", "/", 1)

    if "github.com" in normalized:
        return RemoteUrl(f"{normalized}/commit/{commit_hash}")
    if "gitlab" in normalized:
        return RemoteUrl(f"{normalized}/-/commit/{commit_hash}")
    if "bitbucket" in normalized:
        return RemoteUrl(f"{normalized}/commits/{commit_hash}")
    return None
