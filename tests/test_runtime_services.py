from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from save_my_jupyter.adapters.labarchives import LabArchivesAdapter
from save_my_jupyter.adapters.path_templates import render_root_path_template
from save_my_jupyter.domain import (
    CellId,
    CommitHash,
    CommitMode,
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
    RepoHost,
    RepoRootPath,
    ResolvedRepoContext,
    ResolvedSnapshotPlan,
    RunFingerprint,
    SnapshotId,
    SnapshotRecord,
    SnapshotSource,
    UserId,
    UserMetadata,
)
from save_my_jupyter.errors import LabArchivesWriteError
from save_my_jupyter.git.service import DefaultGitService
from save_my_jupyter.services.auth import AuthServiceImpl, LabArchivesSession
from save_my_jupyter.watchers.service import DefaultWatchService

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


class FakeLabApiClient:
    def __init__(self) -> None:
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

    def Client(self) -> FakeLabApiClient:  # noqa: N802
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

    def Client(self) -> FakeLabApiClient:  # noqa: N802
        return TlsFailingLabApiClient()


class LoginFailingLabApiClient(FakeLabApiClient):
    def login(self, email: str, auth_code: str) -> FakeLabApiUser:
        del email, auth_code
        raise RuntimeError("unexpected login failure")


class LoginFailingLabApiModule:
    AuthenticationError = FakeLabApiAuthError

    def Client(self) -> FakeLabApiClient:  # noqa: N802
        return LoginFailingLabApiClient()


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

    class TextEntry:
        pass

    class PlainTextEntry:
        pass

    class AttachmentEntry:
        pass

    Attachment = FakeAttachment

    def Client(self) -> FakeLabApiClient:  # noqa: N802
        return FakeLabApiClient()


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
        _entry_type: type[object],
        name: str,
        *,
        if_exists: str,
    ) -> FakePage:
        del if_exists
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
            repo_host=RepoHost.UNKNOWN,
            head_commit=None,
            is_dirty=True,
        ),
        path_rule=None,
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
        "save_my_jupyter.services.auth.load_labapi",
        lambda: FakeLabApiModule(),
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

    reloaded_status = reloaded_service.get_auth_status("user-1")
    assert reloaded_status.status == "unauthenticated"
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


def test_auth_service_reports_missing_server_credentials(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "save_my_jupyter.services.auth.load_labapi",
        lambda: FailingLabApiModule(),
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
        "save_my_jupyter.services.auth.load_labapi",
        lambda: TlsFailingLabApiModule(),
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
        "save_my_jupyter.services.auth.load_labapi",
        lambda: LoginFailingLabApiModule(),
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


def test_watch_service_polls_files_and_emits_requests() -> None:
    root = _make_workspace_temp_dir()
    service = DefaultWatchService(poll_interval_seconds=60.0)
    try:
        notebook_path = root / "analysis.ipynb"
        notebook_path.write_text("{}", encoding="utf-8")
        watch_root = root / "outputs"
        watch_root.mkdir()

        service.register_notebook_watch(
            commit_mode=CommitMode.NEVER,
            notebook_context=NotebookContext(
                notebook_path=NotebookPath(str(notebook_path)),
                notebook_name="analysis.ipynb",
            ),
            root=root,
            user_id=UserId("user-1"),
            user_metadata=UserMetadata(),
            watch_paths=(RelativeWatchPath("outputs"),),
        )
        service.stop()

        watched_file = watch_root / "result.txt"
        watched_file.write_text("first", encoding="utf-8")
        created_requests = service.poll_once()
        assert len(created_requests) == 1
        assert (
            str(created_requests[0].watched_path_event.relative_path)
            == "outputs/result.txt"
        )
        assert created_requests[0].watched_path_event.event_type.value == "created"

        watched_file.write_text("second", encoding="utf-8")
        modified_requests = service.poll_once()
        assert len(modified_requests) == 1
        assert modified_requests[0].watched_path_event.event_type.value == "modified"

        watched_file.unlink()
        deleted_requests = service.poll_once()
        assert len(deleted_requests) == 1
        assert deleted_requests[0].watched_path_event.event_type.value == "deleted"
    finally:
        service.stop()
        shutil.rmtree(root, ignore_errors=True)


def test_labarchives_adapter_writes_snapshot_page(
    monkeypatch: MonkeyPatch,
) -> None:
    labapi = FakeLabApiModule()
    monkeypatch.setattr(
        "save_my_jupyter.adapters.labarchives.load_labapi",
        lambda: labapi,
    )

    notebook = FakeDirectory()
    root = _make_workspace_temp_dir()
    try:
        file_path = root / "artifact.txt"
        file_path.write_text("payload", encoding="utf-8")
        figure_bytes = b"\x89PNG\r\n\x1a\nfigure"
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
                repo_host=RepoHost.UNKNOWN,
                head_commit=CommitHash("abc1234"),
                is_dirty=True,
            ),
            path_rule_name="analysis",
            commit_hash=CommitHash("def5678"),
            commit_url="https://git.example.test/commit/def5678",
            dirty_diff="diff --git a/notebook.ipynb b/notebook.ipynb",
            run_fingerprint=RunFingerprint("run-1"),
            trigger_cell_ids=(CellId("cell-1"),),
            executed_cell_ids=(),
            produced_value_summary="42",
            artifacts=(
                NotebookArtifact(
                    display_name="notebook.ipynb",
                    mime_type=MimeType("application/x-ipynb+json"),
                    bytes_payload=b"{}",
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
            ),
            metadata=UserMetadata(run_label="baseline", tags=("baseline",)),
            labarchives_target=LabArchivesTarget(
                notebook_name=LabArchivesNotebookName("Snapshots"),
                root_path=LabArchivesRootPath("Runs/{user_id}/{scope_path}/{run_label}"),
            ),
            extension_version="0.1.0",
        )

        result = adapter.write_snapshot(record, session)
        assert result.status == "persisted"

        target_root = (
            notebook.children["Runs"]
            .children["user-1"]
            .children["analysis"]
            .children["baseline"]
        )
        page = next(iter(target_root.pages.values()))
        created_entry_types = [
            entry_type.__name__ for entry_type, _payload in page.entries.created
        ]
        assert created_entry_types == [
            "TextEntry",
            "PlainTextEntry",
            "PlainTextEntry",
            "PlainTextEntry",
            "PlainTextEntry",
            "AttachmentEntry",
            "AttachmentEntry",
            "AttachmentEntry",
        ]

        summary_entry = _entry_text(page.entries.created[0][1])
        assert "Notebook:</strong> notebook.ipynb" in summary_entry
        assert "Source:</strong> manual" in summary_entry
        assert "Snapshot ID:</strong> snapshot-1" in summary_entry

        metadata_entry = _entry_text(page.entries.created[1][1])
        assert '"commit_hash": "def5678"' in metadata_entry
        assert '"dirty": true' in metadata_entry
        assert '"run_label": "baseline"' in metadata_entry
        assert '"tags": [' in metadata_entry
        assert '"trigger_cell_ids": [' in metadata_entry

        git_info_entry = _entry_text(page.entries.created[2][1])
        assert "head_commit=abc1234" in git_info_entry
        assert "snapshot_commit=def5678" in git_info_entry
        assert "commit_url=https://git.example.test/commit/def5678" in git_info_entry

        execution_entry = _entry_text(page.entries.created[3][1])
        assert execution_entry == "42"

        diff_entry = _entry_text(page.entries.created[4][1])
        assert diff_entry == "diff --git a/notebook.ipynb b/notebook.ipynb"

        attachments = [
            _entry_attachment(payload)
            for _entry_type, payload in page.entries.created[5:]
        ]
        assert [attachment.display_name for attachment in attachments] == [
            "notebook.ipynb",
            "artifact.txt",
            "figure-001.png",
        ]
        assert [attachment.description for attachment in attachments] == [
            "Notebook snapshot",
            "File artifact",
            "Generated figure 1",
        ]
        assert [attachment.mime_type for attachment in attachments] == [
            "application/x-ipynb+json",
            "text/plain",
            "image/png",
        ]
        attachment_payloads = [
            _attachment_bytes(attachment.payload) for attachment in attachments
        ]
        assert attachment_payloads == [
            b"{}",
            b"payload",
            figure_bytes,
        ]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_render_root_path_template_supports_snapshot_variables() -> None:
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
            repo_host=RepoHost.UNKNOWN,
            head_commit=None,
            is_dirty=True,
        ),
        path_rule_name="analysis",
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
                "Runs/{user_id}/{scope_path}/{run_label}/{date}"
            ),
        ),
        extension_version="0.1.0",
    )

    rendered_path = render_root_path_template(
        str(record.labarchives_target.root_path),
        record,
    )

    assert rendered_path == (
        "Runs",
        "user-1",
        "analysis",
        "baseline",
        "2026-04-10",
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


def _entry_text(payload: str | FakeAttachment) -> str:
    assert isinstance(payload, str)
    return payload


def _entry_attachment(payload: str | FakeAttachment) -> FakeAttachment:
    assert isinstance(payload, FakeAttachment)
    return payload


def _attachment_bytes(payload: BytesIO) -> bytes:
    return payload.getvalue()
