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
  parseUserPreferences
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
    watched_paths: []
  });
});

void test("parseSnapshotRequestPayload parses watched path requests", () => {
  const payload = parseSnapshotRequestPayload({
    commit_mode: "never",
    notebook_context: {
      notebook_name: "analysis.ipynb",
      notebook_path: "analysis/analysis.ipynb"
    },
    source: "watched_path",
    user_metadata: {
      extra_fields: {},
      tags: []
    },
    watched_path_event: {
      event_type: "modified",
      relative_path: "outputs/result.csv"
    }
  });

  assert.equal(payload.source, "watched_path");
  assert.equal(payload.watched_path_event.relative_path, "outputs/result.csv");
});

void test("parseSnapshotRequestPayload rejects impossible request combinations", () => {
  assert.throws(() => {
    parseSnapshotRequestPayload({
      commit_mode: "prompt",
      notebook_context: {
        notebook_name: "analysis.ipynb",
        notebook_path: "analysis/analysis.ipynb"
      },
      source: "watched_path",
      user_metadata: {
        extra_fields: {},
        tags: []
      }
    });
  });
});

void test("parseSnapshotSubmissionResult parses accepted payloads", () => {
  const result = parseSnapshotSubmissionResult({
    jobId: "job-1",
    queuePosition: 1,
    status: "accepted"
  });

  assert.equal(result.status, "accepted");
  assert.equal(result.queuePosition, 1);
});

void test("parseAuthStartResponse parses auth bootstrap payloads", () => {
  const result = parseAuthStartResponse({
    authUrl: "https://auth.example.test",
    message: "Open LabArchives to authenticate.",
    requestId: "request-1",
    status: "pending"
  });

  assert.equal(result.status, "pending");
});

void test("parseAuthState preserves stored profile details", () => {
  const result = parseAuthState({
    pendingRequestId: null,
    status: "unauthenticated",
    storedNotebookNames: ["Primary Notebook", "Reference Notes"],
    storedUserEmail: "user@example.com",
    userEmail: null
  });

  assert.equal(result.status, "unauthenticated");
  assert.deepEqual(result.storedNotebookNames, [
    "Primary Notebook",
    "Reference Notes"
  ]);
  assert.equal(result.storedUserEmail, "user@example.com");
});

void test("parseConfigInitResponse parses starter config responses", () => {
  const result = parseConfigInitResponse({
    configPath: "C:/repo/.save-my-jupyter.toml",
    rootDirectory: "C:/repo",
    status: "created"
  });

  assert.equal(result.status, "created");
  assert.equal(result.configPath, "C:/repo/.save-my-jupyter.toml");
});

void test("parseEffectiveState parses state payloads from the backend", () => {
  const state = parseEffectiveState({
    auth: {
      status: "authenticated",
      userEmail: "user@example.com"
    },
    effectiveConfig: {
      allCellsTrigger: true,
      commitMode: "always",
      includeDiffWhenDirty: true,
      includeNotebookFile: true,
      metadataTemplate: {
        owner: "alice"
      },
      stageNotebookOnCommit: true,
      stageWatchedPathsOnCommit: false,
      target: {
        notebookName: "Snapshots",
        rootPath: "Runs"
      },
      watchedPaths: ["outputs"]
    },
    notebookMetadata: {
      all_cells_trigger: true,
      default_metadata: {},
      enabled: true,
      labarchives_target_notebook: null,
      labarchives_target_root_path: null,
      trigger_cell_ids: ["cell-1"],
      watched_paths: ["outputs"]
    },
    pathRule: {
      includePaths: ["outputs"],
      metadataTemplate: {},
      name: "analysis",
      target: {
        notebookName: "Snapshots",
        rootPath: "Runs"
      },
      watchPaths: ["outputs"]
    },
    repo: {
      headCommit: "abc1234",
      isDirty: false,
      relativeNotebookPath: "analysis/notebook.ipynb",
      remoteUrl: "git@github.com:example/repo.git",
      repoHost: "github",
      repoRoot: "/repo"
    },
    repoConfigPath: "/repo/.save-my-jupyter.toml",
    repoConfigLoaded: true
  });

  assert.equal(state.auth.status, "authenticated");
  assert.equal(state.effectiveConfig?.commitMode, "always");
  assert.equal(state.pathRule?.name, "analysis");
  assert.equal(state.repoConfigPath, "/repo/.save-my-jupyter.toml");
});

void test("parseUserPreferences ignores removed experiment context settings", () => {
  const preferences = parseUserPreferences({
    defaultCommitMode: "always",
    defaultExperimentContext: "legacy-hidden-value",
    defaultRunLabel: "run-1",
    defaultTags: ["baseline"],
    rememberCommitChoice: true
  });

  assert.deepEqual(preferences, {
    defaultCommitMode: "always",
    defaultRunLabel: "run-1",
    defaultTags: ["baseline"],
    rememberCommitChoice: true
  });
});
