import assert from "node:assert/strict";
import test from "node:test";

import {
  parseAuthState,
  parseConfigInitResponse,
  parseConfigStatusResponse,
  parseEffectiveState,
  parseAuthStartResponse,
  parseNotebookExtensionMetadata,
  parseSnapshotJobsResponse,
  parseSnapshotPreviewResponse,
  parseSnapshotRequestPayload,
  parseSnapshotSubmissionResult,
  parseUserPreferences,
} from "../src/types";

void test("parseNotebookExtensionMetadata applies defaults", () => {
  const metadata = parseNotebookExtensionMetadata({});

  assert.deepEqual(metadata, {
    all_cells_trigger: false,
    default_metadata: {},
    enabled: true,
    labarchives_target_notebook: null,
    labarchives_target_root_path: null,
    trigger_cell_ids: [],
    watched_paths: [],
  });
});

void test("parseSnapshotRequestPayload parses trigger requests", () => {
  const payload = parseSnapshotRequestPayload({
    commit_mode: "always",
    notebook_context: {
      triggering_cell_id: "cell-1",
      notebook_name: "analysis.ipynb",
      notebook_path: "analysis/analysis.ipynb",
    },
    source: "trigger_cell",
    user_metadata: {
      extra_fields: {},
      tags: [],
    },
  });

  assert.equal(payload.source, "trigger_cell");
  assert.equal(payload.notebook_context.triggering_cell_id, "cell-1");
});

void test("parseSnapshotRequestPayload rejects removed watched-path sources", () => {
  assert.throws(() => {
    parseSnapshotRequestPayload({
      commit_mode: "ask",
      notebook_context: {
        notebook_name: "analysis.ipynb",
        notebook_path: "analysis/analysis.ipynb",
      },
      source: "watched_path",
      user_metadata: {
        extra_fields: {},
        tags: [],
      },
    });
  });
});

void test("parseSnapshotSubmissionResult parses accepted payloads", () => {
  const result = parseSnapshotSubmissionResult({
    jobId: "job-1",
    status: "accepted",
  });

  assert.equal(result.status, "accepted");
  assert.equal(result.queuePosition, 0);
  assert.equal(result.coalescedInto, null);
  assert.equal(result.labarchivesDirectoryName, null);
  assert.equal(result.labarchivesMetaPageId, null);
  assert.equal(result.labarchivesMetaPageName, null);
  assert.equal(result.labarchivesPageCount, null);
  assert.equal(result.labarchivesPageId, null);
  assert.equal(result.labarchivesPageName, null);
});

void test("parseSnapshotSubmissionResult accepts snake-case accepted payloads", () => {
  const result = parseSnapshotSubmissionResult({
    coalesced_into: "job-1",
    job_id: "job-2",
    queue_position: 2,
    status: "accepted",
  });

  assert.equal(result.status, "accepted");
  assert.equal(result.jobId, "job-2");
  assert.equal(result.coalescedInto, "job-1");
  assert.equal(result.queuePosition, 2);
});

void test("parseSnapshotJobsResponse applies activity defaults", () => {
  const result = parseSnapshotJobsResponse({
    jobs: [
      {
        displayMessage: "Snapshot saved. Job job-1.",
        jobId: "job-1",
        notebookPath: "analysis.ipynb",
        runOutcome: "success",
        source: "manual",
        state: "persisted",
        submittedAt: "2026-05-26T12:00:00+00:00",
      },
    ],
  });

  const [job] = result.jobs;
  assert.ok(job);
  assert.equal(job.jobId, "job-1");
  assert.equal(job.commitHash, null);
  assert.equal(job.directoryUrl, null);
  assert.equal(job.pageCount, null);
});

void test("parseSnapshotSubmissionResult parses multi-page LabArchives payloads", () => {
  const result = parseSnapshotSubmissionResult({
    jobId: "job-1",
    labarchivesDirectoryName: "2026-04-10T15-00-00.000_snapshot-1",
    labarchivesMetaPageId: "page-1",
    labarchivesMetaPageName: "00 Metadata",
    labarchivesPageCount: 3,
    labarchivesPageId: "page-1",
    labarchivesPageName: "00 Metadata",
    queuePosition: 1,
    status: "accepted",
  });

  assert.equal(result.status, "accepted");
  assert.equal(
    result.labarchivesDirectoryName,
    "2026-04-10T15-00-00.000_snapshot-1",
  );
  assert.equal(result.labarchivesMetaPageId, "page-1");
  assert.equal(result.labarchivesMetaPageName, "00 Metadata");
  assert.equal(result.labarchivesPageCount, 3);
  assert.equal(result.labarchivesPageId, "page-1");
  assert.equal(result.labarchivesPageName, "00 Metadata");
});

void test("parseSnapshotSubmissionResult parses coalesced accepted payloads", () => {
  const result = parseSnapshotSubmissionResult({
    coalescedInto: "job-1",
    jobId: "job-2",
    status: "accepted",
  });

  assert.equal(result.status, "accepted");
  assert.equal(result.coalescedInto, "job-1");
});

void test("parseAuthStartResponse parses auth bootstrap payloads", () => {
  const result = parseAuthStartResponse({
    authUrl: "https://auth.example.test",
    message: "Open LabArchives to authenticate.",
    requestId: "request-1",
    status: "pending",
  });

  assert.equal(result.status, "pending");
});

void test("parseAuthState preserves stored profile details", () => {
  const result = parseAuthState({
    pendingRequestId: null,
    status: "unauthenticated",
    storedNotebookNames: ["Primary Notebook", "Reference Notes"],
    storedUserEmail: "user@example.com",
    userEmail: null,
  });

  assert.equal(result.status, "unauthenticated");
  assert.deepEqual(result.storedNotebookNames, [
    "Primary Notebook",
    "Reference Notes",
  ]);
  assert.equal(result.storedUserEmail, "user@example.com");
});

void test("parseConfigInitResponse parses starter config responses", () => {
  const result = parseConfigInitResponse({
    configPath: ".save-my-jupyter.toml",
    message: "Created starter config at .save-my-jupyter.toml.",
    rootDirectory: "",
    status: "created",
  });

  assert.equal(result.status, "created");
  assert.equal(result.configPath, ".save-my-jupyter.toml");
  assert.equal(result.message, "Created starter config at .save-my-jupyter.toml.");
});

void test("parseConfigStatusResponse parses starter config status responses", () => {
  const result = parseConfigStatusResponse({
    configPath: "project/.save-my-jupyter.toml",
    exists: false,
    rootDirectory: "project",
  });

  assert.equal(result.exists, false);
  assert.equal(result.rootDirectory, "project");
});

void test("parseEffectiveState parses state payloads from the backend", () => {
  const state = parseEffectiveState({
    auth: {
      status: "authenticated",
      userEmail: "user@example.com",
    },
    effectiveConfig: {
      allCellsTrigger: true,
      commitMessageTemplate: "snapshot: {notebook_name} {timestamp}",
      commitMode: "always",
      includeDiffWhenDirty: true,
      includeNotebookFile: true,
      metadataTemplate: {
        owner: "alice",
      },
      stageNotebookOnCommit: true,
      stageWatchedPathsOnCommit: false,
      target: {
        notebookName: "Snapshots",
        rootPath: "Runs",
      },
      watchedPaths: ["outputs"],
    },
    notebookMetadata: {
      all_cells_trigger: true,
      default_metadata: {},
      enabled: true,
      labarchives_target_notebook: null,
      labarchives_target_root_path: null,
      trigger_cell_ids: ["cell-1"],
      watched_paths: ["outputs"],
    },
    repo: {
      headCommit: "abc1234",
      isDirty: false,
      relativeNotebookPath: "analysis/notebook.ipynb",
      remoteUrl: "git@github.com:example/repo.git",
      repoRoot: "/repo",
    },
    repoConfigPath: "/repo/.save-my-jupyter.toml",
    repoConfigLoaded: true,
  });

  assert.equal(state.auth.status, "authenticated");
  assert.equal(
    state.effectiveConfig?.commitMessageTemplate,
    "snapshot: {notebook_name} {timestamp}",
  );
  assert.equal(state.effectiveConfig.commitMode, "always");
  assert.equal(state.repoConfigPath, "/repo/.save-my-jupyter.toml");
});

void test("parseEffectiveState accepts default ask commit mode", () => {
  const state = parseEffectiveState({
    auth: { status: "unauthenticated" },
    effectiveConfig: {
      allCellsTrigger: false,
      commitMessageTemplate: "snapshot: {notebook_name} {timestamp}",
      commitMode: "ask",
      includeDiffWhenDirty: true,
      includeNotebookFile: true,
      metadataTemplate: {},
      stageNotebookOnCommit: true,
      stageWatchedPathsOnCommit: false,
      target: { notebookName: "Jupyter Snapshots", rootPath: "Notebook Log" },
      watchedPaths: [],
    },
    notebookMetadata: null,
    repo: null,
    repoConfigLoaded: false,
    repoConfigPath: null,
  });

  assert.equal(state.effectiveConfig?.commitMode, "ask");
});

void test("parseSnapshotPreviewResponse applies defaults for optional fields", () => {
  const preview = parseSnapshotPreviewResponse({
    generatedAt: "2026-05-26T12:00:00.000Z",
    source: "disk",
    target: { notebookName: "Jupyter Snapshots", rootPath: "Notebook Log" },
  });

  assert.deepEqual(preview.artifacts, []);
  assert.deepEqual(preview.tags, []);
  assert.deepEqual(preview.provenance, {});
  assert.equal(preview.effectiveConfig, null);
  assert.equal(preview.repo, null);
  assert.equal(preview.repoConfigLoaded, false);
  assert.equal(preview.repoConfigPath, null);
  assert.equal(preview.runLabel, null);
  assert.equal(preview.notes, null);
  assert.deepEqual(preview.extraFields, {});
  assert.equal(preview.source, "disk");
});

void test("parseSnapshotPreviewResponse parses artifacts and provenance layers", () => {
  const preview = parseSnapshotPreviewResponse({
    artifacts: [{ kind: "notebook", summary: "Notebook" }],
    effectiveConfig: {
      allCellsTrigger: true,
      commitMessageTemplate: "snapshot: {notebook_name}",
      commitMode: "always",
      includeDiffWhenDirty: true,
      includeNotebookFile: true,
      metadataTemplate: {},
      stageNotebookOnCommit: true,
      stageWatchedPathsOnCommit: true,
      target: { notebookName: "NB", rootPath: "Root" },
      watchedPaths: ["outputs"],
    },
    generatedAt: "2026-05-26T12:00:00.000Z",
    provenance: { targetRootPath: "inferred", commitMode: "user" },
    repo: {
      headCommit: "abcdef123456",
      isDirty: true,
      relativeNotebookPath: "nb.ipynb",
      remoteUrl: null,
      repoRoot: "/repo",
    },
    repoConfigLoaded: true,
    repoConfigPath: "/repo/.save-my-jupyter.toml",
    runLabel: "run-1",
    notes: "operator note",
    extraFields: { operator: "Ada" },
    source: "frontend",
    tags: ["a"],
    target: { notebookName: "NB", rootPath: "Root" },
  });

  assert.equal(preview.artifacts[0]?.kind, "notebook");
  assert.equal(preview.provenance["targetRootPath"], "inferred");
  assert.equal(preview.provenance["commitMode"], "user");
  assert.equal(preview.effectiveConfig?.commitMode, "always");
  assert.equal(preview.repo?.repoRoot, "/repo");
  assert.equal(preview.repoConfigLoaded, true);
  assert.equal(preview.notes, "operator note");
  assert.deepEqual(preview.extraFields, { operator: "Ada" });
});

void test("parseSnapshotPreviewResponse accepts legacy request source", () => {
  const preview = parseSnapshotPreviewResponse({
    generatedAt: "2026-05-26T12:00:00.000Z",
    source: "request",
    target: { notebookName: "NB", rootPath: "Root" },
  });

  assert.equal(preview.source, "frontend");
});

void test("parseSnapshotPreviewResponse rejects unknown provenance layers", () => {
  assert.throws(() => {
    parseSnapshotPreviewResponse({
      generatedAt: "2026-05-26T12:00:00.000Z",
      provenance: { targetRootPath: "made-up-layer" },
      source: "frontend",
      target: { notebookName: "NB", rootPath: "Root" },
    });
  });
});

void test("parseUserPreferences ignores removed experiment context settings", () => {
  const preferences = parseUserPreferences({
    defaultCommitMode: "prompt",
    defaultExperimentContext: "legacy-hidden-value",
    defaultRunLabel: "run-1",
    defaultTags: ["baseline"],
    rememberCommitChoice: true,
  });

  assert.deepEqual(preferences, {
    defaultCommitMode: "ask",
    defaultRunLabel: "run-1",
    defaultTags: ["baseline"],
    rememberCommitChoice: true,
  });
});
