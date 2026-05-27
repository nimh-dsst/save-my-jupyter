"""Pure serialization of domain results into the JSON the frontend parses
(contracts C-API-02/04, C-CONFIG-02/11, C-DEST-05). No Tornado; the wire shapes
are unit-tested directly and must match the zod schemas in `src/types.ts`."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING

from save_my_jupyter.domain.queue import Accepted, Coalesced, Rejected

if TYPE_CHECKING:
    from save_my_jupyter.domain.activity import ActivityRecord
    from save_my_jupyter.domain.capture import CapturePlan
    from save_my_jupyter.domain.config import EffectiveConfig
    from save_my_jupyter.domain.errors import SnapshotError
    from save_my_jupyter.domain.provenance import ConfigLayer
    from save_my_jupyter.domain.queue import AdmissionDecision
    from save_my_jupyter.domain.repo import RepoContext


def serialize_error(error: SnapshotError) -> dict[str, object]:
    return {
        "error": {
            "code": error.code,
            "message": str(error),
            "context": dict(error.context),
        }
    }


def serialize_submission(decision: AdmissionDecision) -> dict[str, object]:
    match decision:
        case Accepted(job_id=job_id):
            return {"jobId": job_id, "status": "accepted"}
        case Coalesced(job_id=job_id, coalesced_into=coalesced_into):
            return {
                "jobId": job_id,
                "status": "accepted",
                "coalescedInto": coalesced_into,
            }
        case Rejected(reason_code=reason_code, message=message):
            return {
                "status": "rejected",
                "reasonCode": reason_code,
                "message": message,
            }


def serialize_activity(record: ActivityRecord) -> dict[str, object]:
    return {
        "jobId": record.job_id,
        "submittedAt": record.submitted_at.isoformat(),
        "completedAt": _iso_or_none(record.completed_at),
        "source": record.source.value,
        "notebookPath": record.notebook_path,
        "state": record.state.value,
        "runOutcome": record.run_outcome.value,
        "snapshotId": record.snapshot_id,
        "commitHash": record.commit_hash,
        "commitUrl": record.commit_url,
        "directoryName": record.directory_name,
        "directoryUrl": record.directory_url,
        "metaPageId": record.meta_page_id,
        "metaPageName": record.meta_page_name,
        "pageCount": record.page_count,
        "errorCode": record.error_code,
        "errorMessage": record.error_message,
        "displayMessage": record.display_message,
    }


def serialize_activity_list(
    records: tuple[ActivityRecord, ...],
) -> dict[str, object]:
    return {"jobs": [serialize_activity(record) for record in records]}


def serialize_preview(
    *,
    plan: CapturePlan,
    provenance: Mapping[str, ConfigLayer],
    effective: EffectiveConfig,
    repo: RepoContext,
    repo_config_path: str | None,
    repo_config_loaded: bool,
    notes: str | None,
    extra_fields: Mapping[str, str],
    generated_at: datetime,
    source: str,
) -> dict[str, object]:
    serialized_provenance = {
        _camel(key): layer.value for key, layer in provenance.items()
    }
    if plan.run_label_provenance is not None:
        serialized_provenance["runLabel"] = plan.run_label_provenance.value
    return {
        "artifacts": [
            {"kind": artifact.kind.value, "summary": artifact.summary}
            for artifact in plan.artifacts
        ],
        "generatedAt": generated_at.isoformat(),
        "provenance": serialized_provenance,
        "effectiveConfig": _serialize_effective_config(effective),
        "extraFields": dict(extra_fields),
        "notes": notes,
        "repo": _serialize_repo(repo),
        "repoConfigPath": repo_config_path,
        "repoConfigLoaded": repo_config_loaded,
        "runLabel": plan.run_label,
        "source": source,
        "tags": list(plan.tags),
        "target": {
            "notebookName": plan.target.notebook_name,
            "rootPath": plan.target.root_path,
        },
    }


def _serialize_effective_config(config: EffectiveConfig) -> dict[str, object]:
    return {
        "allCellsTrigger": config.all_cells_trigger,
        "commitMessageTemplate": config.commit_message_template,
        "commitMode": config.commit_mode.value,
        "includeDiffWhenDirty": config.include_diff_when_dirty,
        "includeNotebookFile": config.include_notebook_file,
        "metadataTemplate": dict(config.metadata_template),
        "stageNotebookOnCommit": config.stage_notebook_on_commit,
        "stageWatchedPathsOnCommit": config.stage_watched_paths_on_commit,
        "target": {
            "notebookName": config.target.notebook_name,
            "rootPath": config.target.root_path,
        },
        "watchedPaths": list(config.watched_paths),
    }


def _serialize_repo(repo: RepoContext) -> dict[str, object]:
    return {
        "headCommit": repo.head_commit,
        "isDirty": repo.is_dirty,
        "relativeNotebookPath": repo.relative_notebook_path,
        "remoteUrl": repo.remote_url,
        "repoRoot": repo.repo_root,
    }


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _camel(snake: str) -> str:
    head, *rest = snake.split("_")
    return head + "".join(word.capitalize() for word in rest)
