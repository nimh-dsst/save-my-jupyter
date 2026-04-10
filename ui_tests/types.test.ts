import assert from "node:assert/strict";
import test from "node:test";

import {
  parseEffectiveState,
  parseAuthStartResponse,
  parseNotebookExtensionMetadata,
  parseSnapshotRequestPayload,
  parseSnapshotSubmissionResult
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
    repoConfigLoaded: true
  });

  assert.equal(state.auth.status, "authenticated");
  assert.equal(state.effectiveConfig?.commitMode, "always");
  assert.equal(state.pathRule?.name, "analysis");
});
