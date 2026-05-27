from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from save_my_jupyter.adapters.labarchives import (
    LabArchivesAdapter,
    _format_page_name,
)
from save_my_jupyter.adapters.path_templates import render_root_path_template
from save_my_jupyter.domain import (
    CellId,
    CommitHash,
    CommitMode,
    DiffArtifact,
    EffectiveConfig,
    FigureArtifact,
    FileArtifact,
    LabArchivesNotebookName,
    LabArchivesRootPath,
    LabArchivesTarget,
    ManualSnapshotRequest,
    MimeType,
    NotebookArtifact,
    NotebookContext,
    NotebookPath,
    RelativeRepoPath,
    RelativeWatchPath,
    RepoRootPath,
    ResolvedRepoContext,
    ResolvedSnapshotPlan,
    RunFingerprint,
    SnapshotFailed,
    SnapshotId,
    SnapshotPersisted,
    SnapshotRecord,
    SnapshotSource,
    UserId,
    UserMetadata,
)
from save_my_jupyter.errors import LabArchivesWriteError
from save_my_jupyter.git.service import DefaultGitService
from save_my_jupyter.services.auth import AuthServiceImpl, LabArchivesSession

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


class FakeLabApiClient:
    def __init__(self, *, base_url: str | None = None) -> None:
        self._base_url = base_url
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def generate_auth_url(self, callback_url: str) -> str:
        return f"https://auth.example.test?callback={callback_url}"

    def login(self, email: str, auth_code: str) -> FakeLabApiUser:
        return FakeLabApiUser(email=email, auth_code=auth_code)


class FakeLabApiAuthError(Exception):
    pass


class FakeLabApiTlsError(Exception):
    pass


class FakeLabApiNotebook:
    def __init__(self, notebook_id: str, notebook_name: str, is_default: bool) -> None:
        self.id = notebook_id
        self.name = notebook_name
        self.is_default = is_default


class FakeLabApiNotebookCollection:
    def __init__(self, notebooks: tuple[FakeLabApiNotebook, ...]) -> None:
        self._notebooks = notebooks

    def all_values(self) -> list[FakeLabApiNotebook]:
        return list(self._notebooks)


class FakeLabApiUser:
    def __init__(self, *, email: str, auth_code: str) -> None:
        self.auth_code = auth_code
        self.email = email
        self.id = "labarchives-user-123"
        self.notebooks = FakeLabApiNotebookCollection(
            (
                FakeLabApiNotebook("nb-1", "Primary Notebook", True),
                FakeLabApiNotebook("nb-2", "Reference Notes", False),
            )
        )


class FailingLabApiModule:
    AuthenticationError = FakeLabApiAuthError

    def Client(  # noqa: N802
        self,
        base_url: str | None = None,
    ) -> FakeLabApiClient:
        del base_url
        raise self.AuthenticationError(
            "ACCESS_KEYID or ACCESS_PWD environment variables not set.",
        )


class TlsFailingLabApiClient(FakeLabApiClient):
    def login(self, email: str, auth_code: str) -> FakeLabApiUser:
        del email, auth_code
        raise FakeLabApiTlsError(
            "Could not find a suitable TLS CA certificate bundle, "
            "invalid path: C:/broken/cacert.pem",
        )


class TlsFailingLabApiModule:
    AuthenticationError = FakeLabApiAuthError

    def Client(  # noqa: N802
        self,
        base_url: str | None = None,
    ) -> FakeLabApiClient:
        return TlsFailingLabApiClient(base_url=base_url)


class LoginFailingLabApiClient(FakeLabApiClient):
    def login(self, email: str, auth_code: str) -> FakeLabApiUser:
        del email, auth_code
        raise RuntimeError("unexpected login failure")


class LoginFailingLabApiModule:
    AuthenticationError = FakeLabApiAuthError

    def Client(  # noqa: N802
        self,
        base_url: str | None = None,
    ) -> FakeLabApiClient:
        return LoginFailingLabApiClient(base_url=base_url)


class FakeAttachment:
    def __init__(
        self,
        payload: BytesIO,
        mime_type: str,
        display_name: str,
        description: str,
    ) -> None:
        self.description = description
        self.display_name = display_name
        self.mime_type = mime_type
        self.payload = payload


class FakeLabApiModule:
    class InsertBehavior:
        Raise = "raise"

    class NotebookPage:
        pass

    class NotebookDirectory:
        pass

    class TextEntry:
        pass

    class PlainTextEntry:
        pass

    class AttachmentEntry:
        pass

    AuthenticationError = FakeLabApiAuthError
    Attachment = FakeAttachment

    def Client(  # noqa: N802
        self,
        base_url: str | None = None,
    ) -> FakeLabApiClient:
        return FakeLabApiClient(base_url=base_url)


class FakeKeyringBackend:
    def __init__(self) -> None:
        self.passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.passwords.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.passwords[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        self.passwords.pop((service_name, username), None)


class FakeEntries:
    def __init__(self) -> None:
        self.created: list[tuple[type[object], str | FakeAttachment]] = []

    def create(
        self,
        entry_type: type[object],
        payload: str | FakeAttachment,
    ) -> str | FakeAttachment:
        self.created.append((entry_type, payload))
        return payload


class FakePage:
    def __init__(self, page_id: str) -> None:
        self.entries = FakeEntries()
        self.id = page_id


class FakeDirectory:
    def __init__(self) -> None:
        self.children: dict[str, FakeDirectory] = {}
        self.pages: dict[str, FakePage] = {}

    def dir(self, name: str) -> FakeDirectory:
        child = self.children.get(name)
        if child is None:
            child = FakeDirectory()
            self.children[name] = child
        return child

    def create(
        self,
        entry_type: type[object],
        name: str,
        *,
        if_exists: str,
    ) -> FakeDirectory | FakePage:
        assert if_exists == FakeLabApiModule.InsertBehavior.Raise
        if entry_type.__name__ == "NotebookDirectory":
            child = FakeDirectory()
            self.children[name] = child
            return child
        page = FakePage(page_id=f"page-{name}")
        self.pages[name] = page
        return page


def _effective_config(
    *,
    commit_mode: CommitMode = CommitMode.NEVER,
    watched_paths: tuple[RelativeWatchPath, ...] = (),
) -> EffectiveConfig:
    return EffectiveConfig(
        all_cells_trigger=False,
        commit_mode=commit_mode,
        watched_paths=watched_paths,
        include_notebook_file=True,
        include_diff_when_dirty=True,
        target=LabArchivesTarget(
            notebook_name=LabArchivesNotebookName("Snapshots"),
            root_path=LabArchivesRootPath("Runs"),
        ),
        metadata_template={},
        stage_notebook_on_commit=True,
        stage_watched_paths_on_commit=False,
        commit_message_template="snapshot: {notebook_name} {timestamp}",
    )


def _manual_plan(
    notebook_path: Path,
    *,
    repo_root: Path | None = None,
    watched_paths: tuple[RelativeWatchPath, ...] = (),
    commit_mode: CommitMode = CommitMode.NEVER,
) -> ResolvedSnapshotPlan:
    return ResolvedSnapshotPlan(
        request=ManualSnapshotRequest(
            notebook_context=NotebookContext(
                notebook_path=NotebookPath(str(notebook_path)),
                notebook_name=notebook_path.name,
            ),
            commit_mode=commit_mode,
            user_metadata=UserMetadata(),
        ),
        repo=ResolvedRepoContext(
            repo_root=None if repo_root is None else RepoRootPath(str(repo_root)),
            relative_notebook_path=RelativeRepoPath(notebook_path.name)
            if repo_root is not None
            else None,
            remote_url=None,
            head_commit=None,
            is_dirty=True,
        ),
        effective_config=_effective_config(
            commit_mode=commit_mode,
            watched_paths=watched_paths,
        ),
        run_fingerprint=RunFingerprint("fingerprint-runtime"),
    )


def test_auth_service_can_start_and_complete_auth(
    monkeypatch: MonkeyPatch,
) -> None:
    keyring_backend = FakeKeyringBackend()
    monkeypatch.setattr(
        "save_my_jupyter.services.auth.labapi",
        FakeLabApiModule(),
    )
    service = AuthServiceImpl(keyring_backend=keyring_backend)

    start_result = service.start_auth(
        "user-1",
        "http://localhost/save-my-jupyter/auth/callback",
    )
    assert start_result.status == "pending"
    assert start_result.request_id is not None
    assert start_result.auth_url is not None

    request_id = start_result.request_id
    session = service.complete_auth(
        request_id,
        email="user@example.com",
        auth_code="secret",
    )
    assert session.user_email == "user@example.com"
    active_status = service.get_auth_status("user-1")
    assert active_status.status == "authenticated"
    assert active_status.stored_user_email == "user@example.com"
    assert active_status.stored_notebook_names == (
        "Primary Notebook",
        "Reference Notes",
    )

    reloaded_service = AuthServiceImpl(keyring_backend=keyring_backend)
    stored_profile = reloaded_service.get_stored_profile("user-1")
    assert stored_profile is not None
    assert stored_profile.user_email == "user@example.com"
    assert stored_profile.labarchives_user_id == "labarchives-user-123"
    assert tuple(notebook.notebook_name for notebook in stored_profile.notebooks) == (
        "Primary Notebook",
        "Reference Notes",
    )

    restored_session = reloaded_service.get_authenticated_user("user-1")
    assert restored_session.user_email == "user@example.com"
    assert tuple(
        notebook.name for notebook in restored_session.user.notebooks.all_values()
    ) == (
        "Primary Notebook",
        "Reference Notes",
    )

    reloaded_status = reloaded_service.get_auth_status("user-1")
    assert reloaded_status.status == "authenticated"
    assert reloaded_status.user_email == "user@example.com"
    assert reloaded_status.stored_user_email == "user@example.com"
    assert reloaded_status.stored_notebook_names == (
        "Primary Notebook",
        "Reference Notes",
    )

    reloaded_start = reloaded_service.start_auth(
        "user-1",
        "http://localhost/save-my-jupyter/auth/callback",
    )
    assert "Previously connected as user@example.com." in reloaded_start.message


def test_auth_service_logout_clears_session_and_keyring(
    monkeypatch: MonkeyPatch,
) -> None:
    keyring_backend = FakeKeyringBackend()
    monkeypatch.setattr(
        "save_my_jupyter.services.auth.labapi",
        FakeLabApiModule(),
    )
    service = AuthServiceImpl(keyring_backend=keyring_backend)

    start_result = service.start_auth(
        "user-1",
        "http://localhost/save-my-jupyter/auth/callback",
    )
    assert start_result.request_id is not None
    service.complete_auth(
        start_result.request_id,
        email="user@example.com",
        auth_code="secret",
    )

    assert service.get_auth_status("user-1").status == "authenticated"
    assert keyring_backend.passwords != {}

    service.logout("user-1")

    assert keyring_backend.passwords == {}
    after_status = service.get_auth_status("user-1")
    assert after_status.status == "unauthenticated"
    assert after_status.stored_user_email is None
    assert after_status.stored_notebook_names == ()

    reloaded_service = AuthServiceImpl(keyring_backend=keyring_backend)
    assert reloaded_service.get_stored_profile("user-1") is None


def test_auth_service_restores_profiles_saved_under_legacy_user_id_alias(
    monkeypatch: MonkeyPatch,
) -> None:
    keyring_backend = FakeKeyringBackend()
    monkeypatch.setattr(
        "save_my_jupyter.services.auth.labapi",
        FakeLabApiModule(),
    )
    legacy_user_id = (
        "User(username='user-1', name='user-1', display_name='user-1', "
        "initials=None, avatar_url=None, color='cerulean')"
    )
    service = AuthServiceImpl(keyring_backend=keyring_backend)

    start_result = service.start_auth(
        legacy_user_id,
        "http://localhost/save-my-jupyter/auth/callback",
    )

    restored_session = service.complete_auth(
        start_result.request_id or "",
        email="user@example.com",
        auth_code="secret",
    )
    assert restored_session.user_email == "user@example.com"

    reloaded_service = AuthServiceImpl(keyring_backend=keyring_backend)
    reloaded_status = reloaded_service.get_auth_status(
        "user-1",
        user_id_aliases=(legacy_user_id,),
    )
    assert reloaded_status.status == "authenticated"
    assert reloaded_status.user_email == "user@example.com"

    migrated_profile = reloaded_service.get_stored_profile("user-1")
    assert migrated_profile is not None
    assert migrated_profile.user_email == "user@example.com"


def test_auth_service_reports_missing_server_credentials(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "save_my_jupyter.services.auth.labapi",
        FailingLabApiModule(),
    )
    service = AuthServiceImpl()

    with pytest.raises(LabArchivesWriteError) as exc_info:
        service.start_auth(
            "user-1",
            "http://localhost/save-my-jupyter/auth/callback",
        )

    assert exc_info.value.code == "missing_labarchives_credentials"
    assert "ACCESS_KEYID" in str(exc_info.value)


def test_auth_service_reports_invalid_tls_bundle_during_login(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "save_my_jupyter.services.auth.labapi",
        TlsFailingLabApiModule(),
    )
    service = AuthServiceImpl()

    start_result = service.start_auth(
        "user-1",
        "http://localhost/save-my-jupyter/auth/callback",
    )

    with pytest.raises(LabArchivesWriteError) as exc_info:
        service.complete_auth(
            start_result.request_id or "",
            email="user@example.com",
            auth_code="secret",
        )

    assert exc_info.value.code == "invalid_tls_ca_bundle"
    assert "REQUESTS_CA_BUNDLE" in str(exc_info.value)


def test_auth_service_wraps_unexpected_login_failures(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "save_my_jupyter.services.auth.labapi",
        LoginFailingLabApiModule(),
    )
    service = AuthServiceImpl()

    start_result = service.start_auth(
        "user-1",
        "http://localhost/save-my-jupyter/auth/callback",
    )

    with pytest.raises(LabArchivesWriteError) as exc_info:
        service.complete_auth(
            start_result.request_id or "",
            email="user@example.com",
            auth_code="secret",
        )

    assert exc_info.value.code == "labarchives_authentication_failed"


def test_labarchives_adapter_writes_snapshot_page(
    monkeypatch: MonkeyPatch,
) -> None:
    labapi = FakeLabApiModule()
    monkeypatch.setattr(
        "save_my_jupyter.adapters.labarchives.labapi",
        labapi,
    )

    notebook = FakeDirectory()
    root = _make_workspace_temp_dir()
    try:
        head_commit = CommitHash("0123456789abcdef0123456789abcdef01234567")
        snapshot_commit = CommitHash("89abcdef0123456789abcdef0123456789abcdef")

        file_path = root / "artifact.txt"
        file_path.write_text("payload", encoding="utf-8")
        figure_bytes = b"\x89PNG\r\n\x1a\nfigure"
        notebook_payload = json.dumps(
            {
                "cells": [
                    {
                        "cell_type": "code",
                        "execution_count": 7,
                        "id": "cell-1",
                        "outputs": [
                            {
                                "name": "stdout",
                                "output_type": "stream",
                                "text": "hi\n",
                            }
                        ],
                        "source": "print('hi')\n",
                    }
                ],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        ).encode("utf-8")
        session = LabArchivesSession(
            user_email="user@example.com",
            user=SimpleNamespace(notebooks={"Snapshots": notebook}),
            client=FakeLabApiClient(),
        )
        adapter = LabArchivesAdapter()
        record = SnapshotRecord(
            snapshot_id=SnapshotId("snapshot-1"),
            timestamp=datetime(2026, 4, 10, 15, 0, tzinfo=UTC),
            source=SnapshotSource.MANUAL,
            user_id=UserId("user-1"),
            notebook_context=NotebookContext(
                notebook_path=NotebookPath("analysis/notebook.ipynb"),
                notebook_name="notebook.ipynb",
            ),
            repo=ResolvedRepoContext(
                repo_root=RepoRootPath("C:/repo"),
                relative_notebook_path=RelativeRepoPath("analysis/notebook.ipynb"),
                remote_url=None,
                head_commit=head_commit,
                is_dirty=True,
            ),
            commit_hash=snapshot_commit,
            commit_url=f"https://git.example.test/commit/{snapshot_commit}",
            dirty_diff="diff --git a/notebook.ipynb b/notebook.ipynb",
            run_fingerprint=RunFingerprint("run-1"),
            trigger_cell_ids=(CellId("cell-1"),),
            executed_cell_ids=(),
            produced_value_summary="42",
            artifacts=(
                NotebookArtifact(
                    display_name="notebook.ipynb",
                    mime_type=MimeType("application/x-ipynb+json"),
                    bytes_payload=notebook_payload,
                    local_path=None,
                    relative_path=RelativeRepoPath("analysis/notebook.ipynb"),
                ),
                FileArtifact(
                    display_name="artifact.txt",
                    mime_type=MimeType("text/plain"),
                    local_path=file_path,
                    relative_path=RelativeRepoPath("outputs/artifact.txt"),
                ),
                FigureArtifact(
                    display_name="figure-001.png",
                    mime_type=MimeType("image/png"),
                    figure_index=1,
                    bytes_payload=figure_bytes,
                ),
                DiffArtifact(
                    display_name="working-tree.patch",
                    mime_type=MimeType("text/x-diff"),
                    diff_text=(
                        "diff --git a/outputs/artifact.txt b/outputs/artifact.txt"
                    ),
                ),
            ),
            metadata=UserMetadata(
                experiment_context="screening",
                extra_fields={
                    "condition": "treated",
                    "owner": "alice",
                },
                notes="first line\nsecond line",
                run_label="baseline",
                tags=("baseline",),
            ),
            labarchives_target=LabArchivesTarget(
                notebook_name=LabArchivesNotebookName("Snapshots"),
                root_path=LabArchivesRootPath(
                    "Runs/{user_email}/{scope_path}/{run_label}"
                ),
            ),
            extension_version="0.1.0",
            commit_created=True,
        )

        result = adapter.write_snapshot(record, session)
        assert result.status == "persisted"
        assert isinstance(result, SnapshotPersisted)

        target_root = (
            notebook.children["Runs"]
            .children["user@example.com"]
            .children["analysis"]
            .children["notebook.ipynb"]
            .children["baseline"]
        )
        directory_name = next(iter(target_root.children))
        assert directory_name.startswith("2026-04-10T15-00-00.000")
        assert directory_name.endswith("_snapshot-1")
        snapshot_directory = target_root.children[directory_name]
        assert list(snapshot_directory.pages) == [
            "00 Metadata",
            "01 Notebook - notebook.ipynb",
            "02 File - outputs - artifact.txt",
        ]

        metadata_page = snapshot_directory.pages["00 Metadata"]
        notebook_page = snapshot_directory.pages["01 Notebook - notebook.ipynb"]
        file_page = snapshot_directory.pages["02 File - outputs - artifact.txt"]
        assert result.labarchives_page_id == metadata_page.id
        assert result.labarchives_page_name == "00 Metadata"
        assert result.labarchives_directory_name == directory_name
        assert result.labarchives_meta_page_id == metadata_page.id
        assert result.labarchives_meta_page_name == "00 Metadata"
        assert result.labarchives_page_count == 3

        metadata_entry_types = [
            entry_type.__name__
            for entry_type, _payload in metadata_page.entries.created
        ]
        assert metadata_entry_types == [
            "TextEntry",
            "PlainTextEntry",
            "PlainTextEntry",
            "TextEntry",
            "AttachmentEntry",
        ]

        metadata_entry = _entry_text(metadata_page.entries.created[0][1])
        assert "<table>" in metadata_entry
        assert "<strong>Snapshot Metadata</strong>" in metadata_entry
        assert "Snapshot Metadata" in metadata_entry
        assert "Notebook" in metadata_entry
        assert "notebook.ipynb" in metadata_entry
        assert "Source" in metadata_entry
        assert "manual" in metadata_entry
        assert "Snapshot ID" in metadata_entry
        assert "snapshot-1" in metadata_entry
        assert "Extra Fields" in metadata_entry
        assert "Artifacts" in metadata_entry
        assert "Run fingerprint" in metadata_entry
        assert "run-1" in metadata_entry
        assert "Trigger cells" in metadata_entry
        assert "cell-1" in metadata_entry
        assert "Commit hash" in metadata_entry
        assert f"89abcdef0123 (full: {snapshot_commit})" in metadata_entry
        assert "Commit status" in metadata_entry
        assert "New snapshot commit created" in metadata_entry
        assert "Diff included" in metadata_entry
        assert "Run label" in metadata_entry
        assert "baseline" in metadata_entry
        assert "Experiment context" in metadata_entry
        assert "screening" in metadata_entry
        assert "Tags" in metadata_entry
        assert "Notes" in metadata_entry
        assert "first line" in metadata_entry
        assert "second line" in metadata_entry
        assert "condition" in metadata_entry
        assert "treated" in metadata_entry
        assert "owner" in metadata_entry
        assert "alice" in metadata_entry
        assert "<th>Name</th>" in metadata_entry
        assert "<th>MIME type</th>" not in metadata_entry
        assert "<th>LabArchives page</th>" in metadata_entry
        assert "analysis/notebook.ipynb" in metadata_entry
        assert "artifact.txt" in metadata_entry
        assert "outputs/artifact.txt" in metadata_entry
        assert "figure-001.png" in metadata_entry
        assert "working-tree.patch" in metadata_entry
        assert "00 Metadata" in metadata_entry
        assert "01 Notebook - notebook.ipynb" in metadata_entry
        assert "02 File - outputs - artifact.txt" in metadata_entry

        git_info_entry = _entry_text(metadata_page.entries.created[1][1])
        assert "Git Summary" in git_info_entry
        assert f"{'Repository'.ljust(15)} : repo" in git_info_entry
        assert (
            f"{'Notebook path'.ljust(15)} : analysis/notebook.ipynb" in git_info_entry
        )
        assert f"{'Working tree'.ljust(15)} : Dirty (diff included)" in git_info_entry
        assert (
            f"{'HEAD'.ljust(15)} : 0123456789ab (full: {head_commit})" in git_info_entry
        )
        assert (
            f"{'Snapshot commit'.ljust(15)} : "
            f"89abcdef0123 (full: {snapshot_commit})" in git_info_entry
        )
        assert (
            f"{'Commit status'.ljust(15)} : New snapshot commit created"
            in git_info_entry
        )
        assert (
            f"{'Commit URL'.ljust(15)} : https://git.example.test/commit/"
            f"{snapshot_commit}" in git_info_entry
        )

        execution_entry = _entry_text(metadata_page.entries.created[2][1])
        assert execution_entry == "42"

        diff_entry = _entry_text(metadata_page.entries.created[3][1])
        assert "Working Tree Changes" in diff_entry
        assert "Pre-snapshot HEAD" in diff_entry
        assert "Notebook and configured watched paths only" in diff_entry
        assert "notebook.ipynb" in diff_entry
        assert "No notebook source/text changes" in diff_entry

        patch_attachment = _entry_attachment(metadata_page.entries.created[4][1])
        assert patch_attachment.display_name == "working-tree.patch"
        assert patch_attachment.description == (
            "Filtered working tree patch; notebook JSON and image patches are omitted"
        )
        assert patch_attachment.mime_type == "text/x-diff"
        assert _attachment_bytes(patch_attachment.payload) == (
            b"diff --git a/outputs/artifact.txt b/outputs/artifact.txt"
        )

        notebook_entry_types = [
            entry_type.__name__
            for entry_type, _payload in notebook_page.entries.created
        ]
        assert notebook_entry_types == [
            "TextEntry",
            "AttachmentEntry",
            "AttachmentEntry",
        ]
        notebook_entry = _entry_text(notebook_page.entries.created[0][1])
        assert "Notebook Snapshot" in notebook_entry
        assert "Notebook Diff" in notebook_entry
        assert "Notebook Cells" in notebook_entry
        assert "Cell 1" in notebook_entry
        assert "Execution count" in notebook_entry
        assert "7" in notebook_entry
        assert "print" in notebook_entry
        assert "color:#0f766e" in notebook_entry
        assert "hi" in notebook_entry

        notebook_attachments = [
            _entry_attachment(payload)
            for _entry_type, payload in notebook_page.entries.created[1:]
        ]
        assert [attachment.display_name for attachment in notebook_attachments] == [
            "notebook.ipynb",
            "figure-001.png",
        ]
        assert [attachment.description for attachment in notebook_attachments] == [
            "Notebook snapshot (analysis/notebook.ipynb)",
            "Generated figure 1",
        ]
        assert [attachment.mime_type for attachment in notebook_attachments] == [
            "application/x-ipynb+json",
            "image/png",
        ]
        notebook_attachment_payloads = [
            _attachment_bytes(attachment.payload) for attachment in notebook_attachments
        ]
        assert notebook_attachment_payloads == [
            notebook_payload,
            figure_bytes,
        ]

        file_entry_types = [
            entry_type.__name__ for entry_type, _payload in file_page.entries.created
        ]
        assert file_entry_types == [
            "TextEntry",
            "AttachmentEntry",
        ]
        file_entry = _entry_text(file_page.entries.created[0][1])
        assert "File Snapshot" in file_entry
        assert "File Diff" in file_entry
        assert "Readable Preview" in file_entry
        assert "outputs/artifact.txt" in file_entry
        assert "payload" in file_entry
        file_attachment = _entry_attachment(file_page.entries.created[1][1])
        assert file_attachment.display_name == "artifact.txt"
        assert file_attachment.description == "File artifact (outputs/artifact.txt)"
        assert file_attachment.mime_type == "text/plain"
        assert _attachment_bytes(file_attachment.payload) == b"payload"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_labarchives_adapter_writes_one_page_per_file_artifact(
    monkeypatch: MonkeyPatch,
) -> None:
    labapi = FakeLabApiModule()
    monkeypatch.setattr(
        "save_my_jupyter.adapters.labarchives.labapi",
        labapi,
    )

    notebook = FakeDirectory()
    root = _make_workspace_temp_dir()
    try:
        later_file = root / "b.txt"
        later_file.write_text("bee", encoding="utf-8")
        earlier_file = root / "a.py"
        earlier_file.write_text("print('alpha')\n", encoding="utf-8")
        session = LabArchivesSession(
            user_email="user@example.com",
            user=SimpleNamespace(notebooks={"Snapshots": notebook}),
            client=FakeLabApiClient(),
        )
        record = replace(
            _make_minimal_snapshot_record(
                snapshot_id=SnapshotId("snapshot-files"),
                timestamp=datetime(2026, 4, 10, 15, 0, tzinfo=UTC),
            ),
            artifacts=(
                FileArtifact(
                    display_name="b.txt",
                    mime_type=MimeType("text/plain"),
                    local_path=later_file,
                    relative_path=RelativeRepoPath("outputs/b.txt"),
                ),
                FileArtifact(
                    display_name="a.py",
                    mime_type=MimeType("text/x-python"),
                    local_path=earlier_file,
                    relative_path=RelativeRepoPath("outputs/a.py"),
                ),
            ),
        )

        result = LabArchivesAdapter().write_snapshot(record, session)

        assert result.status == "persisted"
        assert isinstance(result, SnapshotPersisted)
        snapshot_directory = next(iter(notebook.children["Runs"].children.values()))
        assert list(snapshot_directory.pages) == [
            "00 Metadata",
            "01 Notebook - notebook.ipynb",
            "02 File - outputs - a.py",
            "03 File - outputs - b.txt",
        ]
        assert result.labarchives_page_count == 4

        metadata_entry = _entry_text(
            snapshot_directory.pages["00 Metadata"].entries.created[0][1]
        )
        assert "02 File - outputs - a.py" in metadata_entry
        assert "03 File - outputs - b.txt" in metadata_entry

        python_page_entry = _entry_text(
            snapshot_directory.pages["02 File - outputs - a.py"].entries.created[0][1]
        )
        assert "Readable Preview" in python_page_entry
        assert "outputs/a.py" in python_page_entry
        assert "color:#0f766e" in python_page_entry

        text_page_entry = _entry_text(
            snapshot_directory.pages["03 File - outputs - b.txt"].entries.created[0][1]
        )
        assert "outputs/b.txt" in text_page_entry
        assert "bee" in text_page_entry
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_labarchives_adapter_uses_file_artifact_payload_for_preview_and_attachment(
    monkeypatch: MonkeyPatch,
) -> None:
    labapi = FakeLabApiModule()
    monkeypatch.setattr(
        "save_my_jupyter.adapters.labarchives.labapi",
        labapi,
    )

    notebook = FakeDirectory()
    root = _make_workspace_temp_dir()
    try:
        file_path = root / "result.txt"
        file_path.write_text("changed after snapshot", encoding="utf-8")
        session = LabArchivesSession(
            user_email="user@example.com",
            user=SimpleNamespace(notebooks={"Snapshots": notebook}),
            client=FakeLabApiClient(),
        )
        record = replace(
            _make_minimal_snapshot_record(
                snapshot_id=SnapshotId("snapshot-payload"),
                timestamp=datetime(2026, 4, 10, 15, 0, tzinfo=UTC),
            ),
            artifacts=(
                FileArtifact(
                    display_name="result.txt",
                    mime_type=MimeType("text/plain"),
                    local_path=file_path,
                    relative_path=RelativeRepoPath("outputs/result.txt"),
                    bytes_payload=b"captured at snapshot",
                ),
            ),
        )

        result = LabArchivesAdapter().write_snapshot(record, session)

        assert result.status == "persisted"
        snapshot_directory = next(iter(notebook.children["Runs"].children.values()))
        file_page = snapshot_directory.pages["02 File - outputs - result.txt"]
        file_entry = _entry_text(file_page.entries.created[0][1])
        assert "captured at snapshot" in file_entry
        assert "changed after snapshot" not in file_entry
        file_attachment = _entry_attachment(file_page.entries.created[1][1])
        assert _attachment_bytes(file_attachment.payload) == b"captured at snapshot"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_labarchives_adapter_cleans_up_partial_write(
    monkeypatch: MonkeyPatch,
) -> None:
    labapi = FakeLabApiModule()
    monkeypatch.setattr(
        "save_my_jupyter.adapters.labarchives.labapi",
        labapi,
    )

    deletion_log: list[str] = []

    class FailingEntries:
        def __init__(self, page_id: str) -> None:
            self._page_id = page_id

        def create(
            self,
            _entry_type: type[object],
            _payload: object,
        ) -> object:
            error_message = f"entry create failed for page {self._page_id}"
            raise RuntimeError(error_message)

    class DeletableFakePage:
        def __init__(self, page_id: str) -> None:
            self.id = page_id
            self.entries = FailingEntries(page_id)

        def delete(self) -> DeletableFakePage:
            deletion_log.append(self.id)
            return self

    class FakeDirectoryWithDeletablePage:
        def __init__(self, directory_id: str = "dir-root") -> None:
            self.id = directory_id
            self.children: dict[str, FakeDirectoryWithDeletablePage] = {}

        def dir(self, name: str) -> FakeDirectoryWithDeletablePage:
            child = self.children.get(name)
            if child is None:
                child = FakeDirectoryWithDeletablePage(directory_id=f"dir-{name}")
                self.children[name] = child
            return child

        def create(
            self,
            entry_type: type[object],
            name: str,
            *,
            if_exists: str,
        ) -> FakeDirectoryWithDeletablePage | DeletableFakePage:
            assert if_exists == FakeLabApiModule.InsertBehavior.Raise
            if entry_type.__name__ == "NotebookDirectory":
                child = FakeDirectoryWithDeletablePage(directory_id=f"dir-{name}")
                self.children[name] = child
                return child
            return DeletableFakePage(page_id=f"page-{name}")

        def delete(self) -> FakeDirectoryWithDeletablePage:
            deletion_log.append(self.id)
            return self

    notebook = FakeDirectoryWithDeletablePage()
    session = LabArchivesSession(
        user_email="user@example.com",
        user=SimpleNamespace(notebooks={"Snapshots": notebook}),
        client=FakeLabApiClient(),
    )
    record = _make_minimal_snapshot_record(
        snapshot_id=SnapshotId("snapshot-partial"),
        timestamp=datetime(2026, 4, 10, 15, 0, tzinfo=UTC),
    )

    result = LabArchivesAdapter().write_snapshot(record, session)

    assert result.status == "failed"
    assert isinstance(result, SnapshotFailed)
    assert result.error_code == "labarchives_write_failed"
    assert len(deletion_log) == 2
    assert deletion_log[0].startswith("page-")
    assert deletion_log[1].startswith("dir-")


def test_labarchives_adapter_cleans_up_all_pages_after_later_page_failure(
    monkeypatch: MonkeyPatch,
) -> None:
    labapi = FakeLabApiModule()
    monkeypatch.setattr(
        "save_my_jupyter.adapters.labarchives.labapi",
        labapi,
    )

    deletion_log: list[str] = []

    class SelectivelyFailingEntries(FakeEntries):
        def __init__(self, page_id: str) -> None:
            super().__init__()
            self._page_id = page_id

        def create(
            self,
            entry_type: type[object],
            payload: str | FakeAttachment,
        ) -> str | FakeAttachment:
            if "02 File" in self._page_id:
                raise RuntimeError(f"entry create failed for page {self._page_id}")
            return super().create(entry_type, payload)

    class DeletablePage:
        def __init__(self, page_id: str) -> None:
            self.entries = SelectivelyFailingEntries(page_id)
            self.id = page_id

        def delete(self) -> DeletablePage:
            deletion_log.append(self.id)
            return self

    class DeletableDirectory:
        def __init__(self, directory_id: str = "dir-root") -> None:
            self.id = directory_id
            self.children: dict[str, DeletableDirectory] = {}
            self.pages: dict[str, DeletablePage] = {}

        def dir(self, name: str) -> DeletableDirectory:
            child = self.children.get(name)
            if child is None:
                child = DeletableDirectory(directory_id=f"dir-{name}")
                self.children[name] = child
            return child

        def create(
            self,
            entry_type: type[object],
            name: str,
            *,
            if_exists: str,
        ) -> DeletableDirectory | DeletablePage:
            assert if_exists == FakeLabApiModule.InsertBehavior.Raise
            if entry_type.__name__ == "NotebookDirectory":
                child = DeletableDirectory(directory_id=f"dir-{name}")
                self.children[name] = child
                return child
            page = DeletablePage(page_id=f"page-{name}")
            self.pages[name] = page
            return page

        def delete(self) -> DeletableDirectory:
            deletion_log.append(self.id)
            return self

    root = _make_workspace_temp_dir()
    try:
        watched_file = root / "artifact.txt"
        watched_file.write_text("payload", encoding="utf-8")
        notebook = DeletableDirectory()
        session = LabArchivesSession(
            user_email="user@example.com",
            user=SimpleNamespace(notebooks={"Snapshots": notebook}),
            client=FakeLabApiClient(),
        )
        record = replace(
            _make_minimal_snapshot_record(
                snapshot_id=SnapshotId("snapshot-late-failure"),
                timestamp=datetime(2026, 4, 10, 15, 0, tzinfo=UTC),
            ),
            artifacts=(
                NotebookArtifact(
                    display_name="notebook.ipynb",
                    mime_type=MimeType("application/x-ipynb+json"),
                    bytes_payload=b'{"cells":[]}',
                    local_path=None,
                ),
                FileArtifact(
                    display_name="artifact.txt",
                    mime_type=MimeType("text/plain"),
                    local_path=watched_file,
                    relative_path=RelativeRepoPath("outputs/artifact.txt"),
                ),
            ),
        )

        result = LabArchivesAdapter().write_snapshot(record, session)

        assert result.status == "failed"
        assert isinstance(result, SnapshotFailed)
        assert result.error_code == "labarchives_write_failed"
        assert len(deletion_log) == 4
        assert deletion_log[0].startswith("page-02 File")
        assert deletion_log[1].startswith("page-01 Notebook")
        assert deletion_log[2] == "page-00 Metadata"
        assert deletion_log[3].startswith("dir-")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_labarchives_adapter_does_not_delete_existing_snapshot_directory_on_collision(
    monkeypatch: MonkeyPatch,
) -> None:
    labapi = FakeLabApiModule()
    monkeypatch.setattr(
        "save_my_jupyter.adapters.labarchives.labapi",
        labapi,
    )

    deletion_log: list[str] = []

    class ExistingDirectory:
        def __init__(self) -> None:
            self.children: dict[str, ExistingDirectory] = {}

        def dir(self, name: str) -> ExistingDirectory:
            child = self.children.get(name)
            if child is None:
                child = ExistingDirectory()
                self.children[name] = child
            return child

        def create(
            self,
            entry_type: type[object],
            name: str,
            *,
            if_exists: str,
        ) -> ExistingDirectory:
            assert if_exists == FakeLabApiModule.InsertBehavior.Raise
            if entry_type.__name__ == "NotebookDirectory":
                raise RuntimeError(f'NotebookDirectory with name "{name}" exists')
            raise AssertionError("page creation should not be reached")

        def delete(self) -> ExistingDirectory:
            deletion_log.append("deleted-existing-directory")
            return self

    notebook = ExistingDirectory()
    session = LabArchivesSession(
        user_email="user@example.com",
        user=SimpleNamespace(notebooks={"Snapshots": notebook}),
        client=FakeLabApiClient(),
    )
    record = _make_minimal_snapshot_record(
        snapshot_id=SnapshotId("snapshot-collision"),
        timestamp=datetime(2026, 4, 10, 15, 0, tzinfo=UTC),
    )

    result = LabArchivesAdapter().write_snapshot(record, session)

    assert result.status == "failed"
    assert isinstance(result, SnapshotFailed)
    assert result.error_code == "labarchives_write_failed"
    assert deletion_log == []


def test_labarchives_adapter_translates_session_expired_to_distinct_error(
    monkeypatch: MonkeyPatch,
) -> None:
    labapi = FakeLabApiModule()
    monkeypatch.setattr(
        "save_my_jupyter.adapters.labarchives.labapi",
        labapi,
    )

    class ExpiringDirectory:
        def dir(self, _name: str) -> ExpiringDirectory:
            return self

        def create(
            self,
            _entry_type: type[object],
            _name: str,
            *,
            if_exists: str,
        ) -> object:
            assert if_exists == FakeLabApiModule.InsertBehavior.Raise
            raise FakeLabApiAuthError(
                "Session timeout. Sign in again.",
            )

    expiring_notebook = ExpiringDirectory()
    session = LabArchivesSession(
        user_email="user@example.com",
        user=SimpleNamespace(notebooks={"Snapshots": expiring_notebook}),
        client=FakeLabApiClient(),
    )
    record = _make_minimal_snapshot_record(
        snapshot_id=SnapshotId("snapshot-expired"),
        timestamp=datetime(2026, 4, 10, 15, 0, tzinfo=UTC),
    )

    result = LabArchivesAdapter().write_snapshot(record, session)

    assert result.status == "failed"
    assert isinstance(result, SnapshotFailed)
    assert result.error_code == "labarchives_session_expired"
    assert "sign in" in result.message.lower() or "session" in result.message.lower()


def test_format_page_name_disambiguates_snapshots_with_same_timestamp() -> None:
    timestamp = datetime(2026, 4, 10, 15, 0, tzinfo=UTC)
    first = _make_minimal_snapshot_record(
        snapshot_id=SnapshotId("aaaaaaaaaaaa1111"),
        timestamp=timestamp,
    )
    second = _make_minimal_snapshot_record(
        snapshot_id=SnapshotId("bbbbbbbbbbbb2222"),
        timestamp=timestamp,
    )

    first_name = _format_page_name(first)
    second_name = _format_page_name(second)

    assert first_name != second_name
    assert first_name.startswith("2026-04-10T15-00-00.000")
    assert first_name.endswith("_aaaaaaaaaaaa")
    assert second_name.endswith("_bbbbbbbbbbbb")
    assert ":" not in first_name


def _make_minimal_snapshot_record(
    *,
    snapshot_id: SnapshotId,
    timestamp: datetime,
) -> SnapshotRecord:
    return SnapshotRecord(
        snapshot_id=snapshot_id,
        timestamp=timestamp,
        source=SnapshotSource.MANUAL,
        user_id=UserId("user-1"),
        notebook_context=NotebookContext(
            notebook_path=NotebookPath("notebook.ipynb"),
            notebook_name="notebook.ipynb",
        ),
        repo=ResolvedRepoContext(
            repo_root=None,
            relative_notebook_path=None,
            remote_url=None,
            head_commit=None,
            is_dirty=False,
        ),
        commit_hash=None,
        commit_url=None,
        dirty_diff=None,
        run_fingerprint=RunFingerprint("run-1"),
        trigger_cell_ids=(),
        executed_cell_ids=(),
        produced_value_summary=None,
        artifacts=(),
        metadata=UserMetadata(
            experiment_context=None,
            extra_fields={},
            notes=None,
            run_label=None,
            tags=(),
        ),
        labarchives_target=LabArchivesTarget(
            notebook_name=LabArchivesNotebookName("Snapshots"),
            root_path=LabArchivesRootPath("Runs"),
        ),
        extension_version="0.1.0",
    )


def test_labarchives_adapter_renders_notebook_aware_diff_and_ignores_images(
    monkeypatch: MonkeyPatch,
) -> None:
    labapi = FakeLabApiModule()
    monkeypatch.setattr(
        "save_my_jupyter.adapters.labarchives.labapi",
        labapi,
    )

    notebook = FakeDirectory()
    root = _make_workspace_temp_dir()
    try:
        notebook_path = root / "analysis.ipynb"
        code_path = root / "changed.py"
        image_path = root / "figure.png"

        _write_adapter_test_notebook(
            notebook_path,
            source='print("before")\n',
            text_output="before output",
            image_output="YmVmb3JlLWltYWdl",
        )
        code_path.write_text("value = 1\n", encoding="utf-8")
        image_path.write_bytes(b"before-image")

        _run(["git", "init"], root)
        _run(["git", "config", "user.email", "user@example.com"], root)
        _run(["git", "config", "user.name", "Save My Jupyter"], root)
        _run(["git", "add", "."], root)
        _run(["git", "commit", "-m", "initial"], root)
        head_commit = CommitHash(
            _run(["git", "rev-parse", "HEAD"], root).stdout.strip()
        )

        _write_adapter_test_notebook(
            notebook_path,
            source='print("after")\n',
            text_output="after output",
            image_output="YWZ0ZXItaW1hZ2U=",
        )
        code_path.write_text("value = 2\n", encoding="utf-8")
        image_path.write_bytes(b"after-image")

        diff_text = DefaultGitService().generate_diff(
            _manual_plan(
                notebook_path,
                repo_root=root,
                watched_paths=(
                    RelativeWatchPath("changed.py"),
                    RelativeWatchPath("figure.png"),
                ),
            )
        )
        assert diff_text is not None

        session = LabArchivesSession(
            user_email="user@example.com",
            user=SimpleNamespace(notebooks={"Snapshots": notebook}),
            client=FakeLabApiClient(),
        )
        adapter = LabArchivesAdapter()
        record = SnapshotRecord(
            snapshot_id=SnapshotId("snapshot-rich-diff"),
            timestamp=datetime(2026, 4, 10, 15, 0, tzinfo=UTC),
            source=SnapshotSource.MANUAL,
            user_id=UserId("user-1"),
            notebook_context=NotebookContext(
                notebook_path=NotebookPath(str(notebook_path)),
                notebook_name="analysis.ipynb",
            ),
            repo=ResolvedRepoContext(
                repo_root=RepoRootPath(str(root)),
                relative_notebook_path=RelativeRepoPath("analysis.ipynb"),
                remote_url=None,
                head_commit=head_commit,
                is_dirty=True,
            ),
            commit_hash=None,
            commit_url=None,
            dirty_diff=diff_text,
            run_fingerprint=RunFingerprint("run-rich"),
            trigger_cell_ids=(),
            executed_cell_ids=(),
            produced_value_summary=None,
            artifacts=(),
            metadata=UserMetadata(),
            labarchives_target=LabArchivesTarget(
                notebook_name=LabArchivesNotebookName("Snapshots"),
                root_path=LabArchivesRootPath("Runs"),
            ),
            extension_version="0.1.0",
            diff_base_commit=head_commit,
        )

        result = adapter.write_snapshot(record, session)
        assert result.status == "persisted"

        snapshot_directory = next(iter(notebook.children["Runs"].children.values()))
        metadata_page = snapshot_directory.pages["00 Metadata"]
        notebook_page = snapshot_directory.pages["01 Notebook - analysis.ipynb"]
        diff_entry = _entry_text(metadata_page.entries.created[3][1])
        notebook_entry = _entry_text(notebook_page.entries.created[0][1])

        assert "Working Tree Changes" in diff_entry
        assert "<strong>Notebook</strong>: analysis.ipynb" in diff_entry
        assert "Cells: 1 changed" in diff_entry
        assert "print(&quot;before&quot;)" in diff_entry
        assert "print(&quot;after&quot;)" in diff_entry
        assert "before output" in diff_entry
        assert "after output" in diff_entry
        assert "changed.py" in diff_entry
        assert "value = 2" in diff_entry
        assert "value = 1" in diff_entry
        assert "figure.png" not in diff_entry
        assert "image/png" not in diff_entry
        assert "diff --git a/analysis.ipynb b/analysis.ipynb" not in diff_entry
        assert "Notebook Diff" in notebook_entry
        assert "Notebook Cells" in notebook_entry
        assert "print(&quot;before&quot;)" in notebook_entry
        assert "print(&quot;after&quot;)" in notebook_entry
        assert "color:#0f766e" in notebook_entry
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_labarchives_adapter_omits_raw_notebook_json_when_rich_diff_unavailable(
    monkeypatch: MonkeyPatch,
) -> None:
    labapi = FakeLabApiModule()
    monkeypatch.setattr(
        "save_my_jupyter.adapters.labarchives.labapi",
        labapi,
    )

    notebook = FakeDirectory()
    session = LabArchivesSession(
        user_email="user@example.com",
        user=SimpleNamespace(notebooks={"Snapshots": notebook}),
        client=FakeLabApiClient(),
    )
    record = replace(
        _make_minimal_snapshot_record(
            snapshot_id=SnapshotId("snapshot-raw-notebook-diff"),
            timestamp=datetime(2026, 4, 10, 15, 0, tzinfo=UTC),
        ),
        dirty_diff="\n".join(
            [
                "diff --git a/analysis.ipynb b/analysis.ipynb",
                "@@ -1 +1 @@",
                '-{"metadata": {"old": true}}',
                '+{"metadata": {"new": true}}',
            ]
        ),
        repo=ResolvedRepoContext(
            repo_root=None,
            relative_notebook_path=None,
            remote_url=None,
            head_commit=None,
            is_dirty=True,
        ),
    )

    result = LabArchivesAdapter().write_snapshot(record, session)

    assert result.status == "persisted"
    snapshot_directory = next(iter(notebook.children["Runs"].children.values()))
    metadata_page = snapshot_directory.pages["00 Metadata"]
    diff_entry = _entry_text(metadata_page.entries.created[3][1])
    assert "Working Tree Changes" in diff_entry
    assert "No notebook source/text changes" in diff_entry
    assert "diff --git a/analysis.ipynb b/analysis.ipynb" not in diff_entry
    assert "&quot;metadata&quot;" not in diff_entry


def test_render_root_path_template_supports_snapshot_variables() -> None:
    session = LabArchivesSession(
        user_email="user@example.com",
        user=SimpleNamespace(),
        client=FakeLabApiClient(),
    )
    record = SnapshotRecord(
        snapshot_id=SnapshotId("snapshot-1"),
        timestamp=datetime(2026, 4, 10, 15, 0, tzinfo=UTC),
        source=SnapshotSource.MANUAL,
        user_id=UserId("user-1"),
        notebook_context=NotebookContext(
            notebook_path=NotebookPath("analysis/notebook.ipynb"),
            notebook_name="notebook.ipynb",
        ),
        repo=ResolvedRepoContext(
            repo_root=RepoRootPath("C:/repo"),
            relative_notebook_path=RelativeRepoPath("analysis/notebook.ipynb"),
            remote_url=None,
            head_commit=None,
            is_dirty=True,
        ),
        commit_hash=None,
        commit_url=None,
        dirty_diff=None,
        run_fingerprint=RunFingerprint("run-1"),
        trigger_cell_ids=(),
        executed_cell_ids=(),
        produced_value_summary=None,
        artifacts=(),
        metadata=UserMetadata(
            experiment_context="screening",
            run_label="baseline",
            tags=("baseline",),
        ),
        labarchives_target=LabArchivesTarget(
            notebook_name=LabArchivesNotebookName("Snapshots"),
            root_path=LabArchivesRootPath(
                "Runs/{name}/{user_email}/{scope_path}/{run_label}/{date}"
            ),
            project_name="analysis-repo",
        ),
        extension_version="0.1.0",
    )

    rendered_path = render_root_path_template(
        str(record.labarchives_target.root_path),
        record,
        session,
    )

    assert rendered_path == (
        "Runs",
        "analysis-repo",
        "user@example.com",
        "analysis",
        "notebook.ipynb",
        "baseline",
        "2026-04-10",
    )


def test_render_root_path_template_strips_dot_and_trailing_dots() -> None:
    session = _make_template_session(user_email="user@example.com")
    record = _make_template_record(run_label="baseline.")

    rendered_path = render_root_path_template(
        "Runs/./{run_label}/{user_email}",
        record,
        session,
    )

    assert rendered_path == ("Runs", "baseline", "user@example.com")


def test_render_root_path_template_rejects_parent_traversal() -> None:
    session = _make_template_session(user_email="user@example.com")
    record = _make_template_record(run_label="../admin")

    with pytest.raises(LabArchivesWriteError) as exc_info:
        render_root_path_template("Runs/{run_label}", record, session)

    assert exc_info.value.code == "unsafe_labarchives_target_path"


def test_render_root_path_template_rejects_drive_letter() -> None:
    session = _make_template_session(user_email="C:")
    record = _make_template_record(run_label="baseline")

    with pytest.raises(LabArchivesWriteError) as exc_info:
        render_root_path_template("Runs/{user_email}/{run_label}", record, session)

    assert exc_info.value.code == "unsafe_labarchives_target_path"


def test_render_root_path_template_rejects_colon_in_segment() -> None:
    session = _make_template_session(user_email="user@example.com")
    record = _make_template_record(run_label="bad:label")

    with pytest.raises(LabArchivesWriteError) as exc_info:
        render_root_path_template("Runs/{run_label}", record, session)

    assert exc_info.value.code == "unsafe_labarchives_target_path"


def _make_template_session(*, user_email: str) -> LabArchivesSession:
    return LabArchivesSession(
        user_email=user_email,
        user=SimpleNamespace(),
        client=FakeLabApiClient(),
    )


def _make_template_record(*, run_label: str) -> SnapshotRecord:
    return SnapshotRecord(
        snapshot_id=SnapshotId("snapshot-1"),
        timestamp=datetime(2026, 4, 10, 15, 0, tzinfo=UTC),
        source=SnapshotSource.MANUAL,
        user_id=UserId("user-1"),
        notebook_context=NotebookContext(
            notebook_path=NotebookPath("notebook.ipynb"),
            notebook_name="notebook.ipynb",
        ),
        repo=ResolvedRepoContext(
            repo_root=None,
            relative_notebook_path=None,
            remote_url=None,
            head_commit=None,
            is_dirty=False,
        ),
        commit_hash=None,
        commit_url=None,
        dirty_diff=None,
        run_fingerprint=RunFingerprint("run-1"),
        trigger_cell_ids=(),
        executed_cell_ids=(),
        produced_value_summary=None,
        artifacts=(),
        metadata=UserMetadata(
            experiment_context=None,
            extra_fields={},
            notes=None,
            run_label=run_label,
            tags=(),
        ),
        labarchives_target=LabArchivesTarget(
            notebook_name=LabArchivesNotebookName("Snapshots"),
            root_path=LabArchivesRootPath("Runs"),
            project_name="analysis-repo",
        ),
        extension_version="0.1.0",
    )


def test_git_service_stages_only_snapshot_targets() -> None:
    repo_root = _make_workspace_temp_dir()
    try:
        notebook_path = repo_root / "analysis.ipynb"
        notebook_path.write_text("{}", encoding="utf-8")
        unrelated_path = repo_root / "README.txt"
        unrelated_path.write_text("base", encoding="utf-8")

        _run(["git", "init"], repo_root)
        _run(["git", "config", "user.email", "user@example.com"], repo_root)
        _run(["git", "config", "user.name", "Save My Jupyter"], repo_root)
        _run(["git", "add", "."], repo_root)
        _run(["git", "commit", "-m", "initial"], repo_root)

        notebook_path.write_text('{"cells":[]}', encoding="utf-8")
        unrelated_path.write_text("changed", encoding="utf-8")

        service = DefaultGitService()
        plan = _manual_plan(notebook_path, repo_root=repo_root)
        service.stage_snapshot_paths(plan)
        staged_paths = _run(
            ["git", "diff", "--cached", "--name-only"],
            repo_root,
        ).stdout.splitlines()

        assert staged_paths == ["analysis.ipynb"]

        diff_text = service.generate_diff(plan)
        assert diff_text is not None
        assert "analysis.ipynb" in diff_text
        assert "README.txt" not in diff_text
    finally:
        shutil.rmtree(repo_root, ignore_errors=True)


def test_git_service_stages_changed_repo_config_with_snapshot_targets() -> None:
    repo_root = _make_workspace_temp_dir()
    try:
        notebook_path = repo_root / "analysis.ipynb"
        notebook_path.write_text("{}", encoding="utf-8")
        config_path = repo_root / ".save-my-jupyter.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[project]",
                    'name = "runtime-tests"',
                    "",
                    "[git]",
                    "stage_notebook_on_commit = true",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        unrelated_path = repo_root / "README.txt"
        unrelated_path.write_text("base", encoding="utf-8")

        _run(["git", "init"], repo_root)
        _run(["git", "config", "user.email", "user@example.com"], repo_root)
        _run(["git", "config", "user.name", "Save My Jupyter"], repo_root)
        _run(["git", "add", "."], repo_root)
        _run(["git", "commit", "-m", "initial"], repo_root)

        notebook_path.write_text('{"cells":[]}', encoding="utf-8")
        config_path.write_text(
            "\n".join(
                [
                    "[project]",
                    'name = "runtime-tests"',
                    "",
                    "[git]",
                    "stage_notebook_on_commit = false",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        unrelated_path.write_text("changed", encoding="utf-8")

        service = DefaultGitService()
        plan = _manual_plan(notebook_path, repo_root=repo_root)
        service.stage_snapshot_paths(plan)
        staged_paths = _run(
            ["git", "diff", "--cached", "--name-only"],
            repo_root,
        ).stdout.splitlines()

        assert staged_paths == [".save-my-jupyter.toml", "analysis.ipynb"]
    finally:
        shutil.rmtree(repo_root, ignore_errors=True)


def test_git_service_includes_untracked_watched_files_in_diff() -> None:
    repo_root = _make_workspace_temp_dir()
    try:
        notebook_path = repo_root / "analysis.ipynb"
        notebook_path.write_text("{}", encoding="utf-8")
        package_root = repo_root / "pkg"
        package_root.mkdir()

        _run(["git", "init"], repo_root)
        _run(["git", "config", "user.email", "user@example.com"], repo_root)
        _run(["git", "config", "user.name", "Save My Jupyter"], repo_root)
        _run(["git", "add", "analysis.ipynb"], repo_root)
        _run(["git", "commit", "-m", "initial"], repo_root)

        watched_file = package_root / "hello.py"
        watched_file.write_text("hi", encoding="utf-8")

        service = DefaultGitService()
        plan = _manual_plan(
            notebook_path,
            repo_root=repo_root,
            watched_paths=(RelativeWatchPath("pkg"),),
        )
        diff_text = service.generate_diff(plan)

        assert diff_text is not None
        assert "diff --git a/pkg/hello.py b/pkg/hello.py" in diff_text
        assert "new file mode 100644" in diff_text
        assert "+++ b/pkg/hello.py" in diff_text
        assert "+hi" in diff_text
        assert "analysis.ipynb" not in diff_text
    finally:
        shutil.rmtree(repo_root, ignore_errors=True)


def test_git_service_generates_diff_before_first_commit() -> None:
    repo_root = _make_workspace_temp_dir()
    try:
        notebook_path = repo_root / "analysis.ipynb"
        notebook_path.write_text("{}", encoding="utf-8")
        outputs_root = repo_root / "outputs"
        outputs_root.mkdir()
        watched_file = outputs_root / "result.txt"
        watched_file.write_text("before first commit", encoding="utf-8")

        _run(["git", "init"], repo_root)

        service = DefaultGitService()
        plan = _manual_plan(
            notebook_path,
            repo_root=repo_root,
            watched_paths=(RelativeWatchPath("outputs"),),
        )
        diff_text = service.generate_diff(plan)

        assert diff_text is not None
        assert "diff --git a/analysis.ipynb b/analysis.ipynb" in diff_text
        assert "diff --git a/outputs/result.txt b/outputs/result.txt" in diff_text
    finally:
        shutil.rmtree(repo_root, ignore_errors=True)


def test_git_service_resolves_repo_state() -> None:
    repo_root = _make_workspace_temp_dir()
    try:
        notebook_dir = repo_root / "analysis"
        notebook_dir.mkdir()
        notebook_path = notebook_dir / "notebook.ipynb"
        notebook_path.write_text("{}", encoding="utf-8")

        _run(["git", "init"], repo_root)
        _run(["git", "config", "user.email", "user@example.com"], repo_root)
        _run(["git", "config", "user.name", "Save My Jupyter"], repo_root)
        _run(
            ["git", "config", "remote.origin.url", "git@github.com:example/repo.git"],
            repo_root,
        )
        _run(["git", "add", "."], repo_root)
        _run(["git", "commit", "-m", "initial"], repo_root)

        notebook_path.write_text('{"cells":[]}', encoding="utf-8")

        repo = DefaultGitService().resolve_repo(str(notebook_path))

        assert repo.repo_root == RepoRootPath(str(repo_root))
        assert repo.relative_notebook_path == RelativeRepoPath(
            "analysis/notebook.ipynb"
        )
        assert repo.remote_url == "git@github.com:example/repo.git"
        assert (
            repo.head_commit
            == _run(
                ["git", "rev-parse", "HEAD"],
                repo_root,
            ).stdout.strip()
        )
        assert repo.is_dirty is True
    finally:
        shutil.rmtree(repo_root, ignore_errors=True)


def test_core_modules_do_not_import_ipython() -> None:
    root = Path(__file__).resolve().parent.parent / "save_my_jupyter"

    offending_lines = tuple(
        f"{path}:{line_number}"
        for path in root.rglob("*.py")
        for line_number, line in _enumerate_lines(path)
        if "IPython.get_ipython" in line or line.startswith("import IPython")
    )

    assert offending_lines == ()


def _enumerate_lines(path: Path) -> Iterator[tuple[int, str]]:
    with path.open(encoding="utf-8") as handle:
        for index, line in enumerate(handle, start=1):
            yield index, line.strip()


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _make_workspace_temp_dir() -> Path:
    root = Path.cwd() / f"tmp-runtime-{uuid4().hex}"
    root.mkdir(parents=True)
    return root


def _write_adapter_test_notebook(
    notebook_path: Path,
    *,
    source: str,
    text_output: str,
    image_output: str,
) -> None:
    notebook_path.write_text(
        json.dumps(
            {
                "cells": [
                    {
                        "cell_type": "code",
                        "id": "cell-1",
                        "metadata": {},
                        "outputs": [
                            {
                                "data": {
                                    "image/png": image_output,
                                    "text/plain": text_output,
                                },
                                "output_type": "display_data",
                            }
                        ],
                        "source": [source],
                    }
                ],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        ),
        encoding="utf-8",
    )


def _entry_text(payload: str | FakeAttachment) -> str:
    assert isinstance(payload, str)
    return payload


def _entry_attachment(payload: str | FakeAttachment) -> FakeAttachment:
    assert isinstance(payload, FakeAttachment)
    return payload


def _attachment_bytes(payload: BytesIO) -> bytes:
    return payload.getvalue()
