import assert from "node:assert/strict";
import test from "node:test";

import {
  parseAuthState,
  parseConfigInitResponse,
  parseEffectiveState,
  parseAuthStartResponse,
  parseNotebookExtensionMetadata,
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
      commit_mode: "prompt",
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
    queuePosition: 1,
    status: "accepted",
  });

  assert.equal(result.status, "accepted");
  assert.equal(result.queuePosition, 1);
  assert.equal(result.labarchivesDirectoryName, null);
  assert.equal(result.labarchivesMetaPageId, null);
  assert.equal(result.labarchivesMetaPageName, null);
  assert.equal(result.labarchivesPageCount, null);
  assert.equal(result.labarchivesPageId, null);
  assert.equal(result.labarchivesPageName, null);
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
    configPath: "C:/repo/.save-my-jupyter.toml",
    rootDirectory: "C:/repo",
    status: "created",
  });

  assert.equal(result.status, "created");
  assert.equal(result.configPath, "C:/repo/.save-my-jupyter.toml");
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

void test("parseUserPreferences ignores removed experiment context settings", () => {
  const preferences = parseUserPreferences({
    defaultCommitMode: "always",
    defaultExperimentContext: "legacy-hidden-value",
    defaultRunLabel: "run-1",
    defaultTags: ["baseline"],
    rememberCommitChoice: true,
  });

  assert.deepEqual(preferences, {
    defaultCommitMode: "always",
    defaultRunLabel: "run-1",
    defaultTags: ["baseline"],
    rememberCommitChoice: true,
  });
});
