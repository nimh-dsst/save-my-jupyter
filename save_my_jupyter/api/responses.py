from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from tornado.escape import xhtml_escape

from save_my_jupyter.config.models import (
    EffectiveConfig,
    LabArchivesTarget,
    NotebookMetadataConfig,
    RepoConfigBootstrapResult,
    ResolvedPathRule,
)
from save_my_jupyter.domain import (
    ResolvedRepoContext,
    SnapshotAccepted,
    SnapshotSubmissionResult,
)
from save_my_jupyter.errors import SaveMyJupyterError
from save_my_jupyter.services.auth import AuthStatusResult

type JsonObject = dict[str, object]

_AUTH_COMPLETION_CHANNEL_NAME = "save-my-jupyter-auth"
_AUTH_COMPLETION_STORAGE_KEY = "save-my-jupyter.auth-event"
_RETURN_TO_JUPYTER_MESSAGE = "You can close this tab and return to JupyterLab."


def build_empty_state_payload(
    *,
    auth_status: AuthStatusResult,
) -> JsonObject:
    return {
        "auth": serialize_auth_status(auth_status),
        "effectiveConfig": None,
        "notebookMetadata": None,
        "pathRule": None,
        "repo": None,
        "repoConfigPath": None,
        "repoConfigLoaded": False,
    }


def build_state_payload(
    *,
    auth_status: AuthStatusResult,
    effective_config: EffectiveConfig,
    notebook_metadata: NotebookMetadataConfig,
    path_rule: ResolvedPathRule | None,
    repo: ResolvedRepoContext | None,
    repo_config_loaded: bool,
    repo_config_path: Path,
) -> JsonObject:
    return {
        "auth": serialize_auth_status(auth_status),
        "effectiveConfig": serialize_effective_config(effective_config),
        "notebookMetadata": serialize_notebook_metadata(notebook_metadata),
        "pathRule": serialize_path_rule(path_rule),
        "repo": serialize_repo(repo),
        "repoConfigPath": str(repo_config_path),
        "repoConfigLoaded": repo_config_loaded,
    }


def serialize_auth_status(auth_status: AuthStatusResult) -> JsonObject:
    return {
        "pendingRequestId": auth_status.pending_request_id,
        "storedNotebookNames": list(auth_status.stored_notebook_names),
        "storedUserEmail": auth_status.stored_user_email,
        "status": auth_status.status,
        "userEmail": auth_status.user_email,
    }


def render_auth_callback_page(
    *,
    message: str,
    notification_message: str | None,
    notification_status: str,
    request_id: str,
    title: str,
) -> str:
    escaped_title = xhtml_escape(title)
    escaped_message = xhtml_escape(message)
    completion_script = _render_auth_completion_script(
        notification_message=notification_message,
        notification_status=notification_status,
        request_id=request_id,
    )
    return (
        "<!doctype html>\n"
        '<html><head><meta charset="utf-8" />'
        f"<title>{escaped_title}</title>"
        "</head><body>"
        f"<h1>{escaped_title}</h1>"
        f"<p>{escaped_message}</p>"
        f"<p>{_RETURN_TO_JUPYTER_MESSAGE}</p>"
        f"<script>{completion_script}</script>"
        "</body></html>"
    )


def serialize_effective_config(
    effective_config: EffectiveConfig,
) -> JsonObject:
    return {
        "allCellsTrigger": effective_config.all_cells_trigger,
        "commitMode": effective_config.commit_mode.value,
        "includeDiffWhenDirty": effective_config.include_diff_when_dirty,
        "includeNotebookFile": effective_config.include_notebook_file,
        "metadataTemplate": _serialize_string_map(effective_config.metadata_template),
        "stageNotebookOnCommit": effective_config.stage_notebook_on_commit,
        "stageWatchedPathsOnCommit": effective_config.stage_watched_paths_on_commit,
        "target": _serialize_target(effective_config.target),
        "watchedPaths": _serialize_paths(effective_config.watched_paths),
    }


def serialize_error(exc: SaveMyJupyterError) -> JsonObject:
    return {
        "code": exc.code,
        "context": exc.context,
        "message": str(exc),
    }


def serialize_notebook_metadata(
    metadata: NotebookMetadataConfig,
) -> JsonObject:
    return {
        "all_cells_trigger": metadata.trigger_mode.value == "all_cells",
        "default_metadata": _serialize_string_map(metadata.default_metadata),
        "enabled": metadata.enabled,
        "labarchives_target_notebook": metadata.labarchives_target_notebook,
        "labarchives_target_root_path": metadata.labarchives_target_root_path,
        "trigger_cell_ids": _serialize_paths(metadata.trigger_cell_ids),
        "watched_paths": _serialize_paths(metadata.watched_paths),
    }


def serialize_path_rule(
    path_rule: ResolvedPathRule | None,
) -> JsonObject | None:
    if path_rule is None:
        return None

    return {
        "includePaths": _serialize_paths(path_rule.include_paths),
        "metadataTemplate": _serialize_string_map(path_rule.metadata_template),
        "name": path_rule.rule_name,
        "target": _serialize_target(path_rule.target),
        "watchPaths": _serialize_paths(path_rule.watch_paths),
    }


def serialize_repo(repo: ResolvedRepoContext | None) -> JsonObject | None:
    if repo is None:
        return None

    return {
        "headCommit": repo.head_commit,
        "isDirty": repo.is_dirty,
        "relativeNotebookPath": repo.relative_notebook_path,
        "remoteUrl": repo.remote_url,
        "repoRoot": repo.repo_root,
    }


def serialize_submission_result(
    result: SnapshotSubmissionResult,
) -> JsonObject:
    if isinstance(result, SnapshotAccepted):
        return {
            "jobId": result.job_id,
            "queuePosition": result.queue_position,
            "status": result.status,
        }

    return {
        "message": result.message,
        "reasonCode": result.reason_code,
        "status": result.status,
    }


def serialize_config_init_result(
    result: RepoConfigBootstrapResult,
) -> JsonObject:
    return {
        "configPath": str(result.config_path),
        "rootDirectory": str(result.root_directory),
        "status": result.status,
    }


def _render_auth_completion_script(
    *,
    notification_message: str | None,
    notification_status: str,
    request_id: str,
) -> str:
    channel_name = json.dumps(_AUTH_COMPLETION_CHANNEL_NAME)
    storage_key = json.dumps(_AUTH_COMPLETION_STORAGE_KEY)
    notification_payload = json.dumps(
        {
            "message": notification_message,
            "requestId": request_id,
            "status": notification_status,
        },
        sort_keys=True,
    )
    return (
        f"const payload = {notification_payload};"
        "try {"
        "  if (typeof BroadcastChannel !== 'undefined') {"
        f"    const channel = new BroadcastChannel({channel_name});"
        "    channel.postMessage(payload);"
        "    channel.close();"
        "  }"
        "} catch (_error) {}"
        "try {"
        f"  window.localStorage.setItem({storage_key}, "
        "JSON.stringify({"
        "message: payload.message, "
        "requestId: payload.requestId, "
        "status: payload.status, "
        "timestamp: Date.now()"
        "}));"
        "} catch (_error) {}"
        "window.setTimeout(() => {"
        "  try { window.close(); } catch (_error) {}"
        "}, 150);"
    )


def _serialize_paths(paths: Iterable[object]) -> list[str]:
    return [str(path) for path in paths]


def _serialize_string_map(mapping: Mapping[str, str]) -> dict[str, str]:
    return dict(mapping)


def _serialize_target(target: LabArchivesTarget | None) -> JsonObject | None:
    if target is None:
        return None

    return {
        "notebookName": target.notebook_name,
        "rootPath": target.root_path,
    }
