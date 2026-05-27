import assert from "node:assert/strict";
import test from "node:test";

import {
  buildDetachedViewState,
  buildLoadedViewState,
  createInitialViewState,
  DEFAULT_METADATA,
  mergeMetadataDefaults,
  normalizeUserMetadata,
} from "../src/panelState";

void test("createInitialViewState returns the default sidebar state", () => {
  const state = createInitialViewState();

  assert.equal(state.notebookPath, null);
  assert.equal(state.auth.status, "unauthenticated");
  assert.equal(state.selectedCommitMode, "prompt");
  assert.deepEqual(state.metadata, DEFAULT_METADATA);
  assert.deepEqual(state.userMetadata.tags, []);
});

void test("normalizeUserMetadata clears experiment context", () => {
  const normalized = normalizeUserMetadata({
    experiment_context: "legacy-value",
    extra_fields: {},
    notes: "notes",
    run_label: "run-1",
    tags: ["baseline"],
  });

  assert.deepEqual(normalized, {
    experiment_context: null,
    extra_fields: {},
    notes: "notes",
    run_label: "run-1",
    tags: ["baseline"],
  });
});

void test("mergeMetadataDefaults combines notebook defaults and user preferences", () => {
  const metadata = {
    ...DEFAULT_METADATA,
    default_metadata: {
      owner: "alice",
    },
  };
  const merged = mergeMetadataDefaults(metadata, {
    defaultCommitMode: "always",
    defaultRunLabel: "baseline",
    defaultTags: ["tag-a"],
    rememberCommitChoice: true,
  });

  assert.deepEqual(merged, {
    experiment_context: null,
    extra_fields: {
      owner: "alice",
    },
    notes: null,
    run_label: "baseline",
    tags: ["tag-a"],
  });
});

void test("buildDetachedViewState resets notebook-specific state", () => {
  const current = createInitialViewState();
  current.notebookPath = "analysis/notebook.ipynb";
  current.statusKind = "success";
  current.statusMessage = "done";
  current.auth.status = "authenticated";
  current.auth.userEmail = "user@example.com";

  const detached = buildDetachedViewState(current, {
    defaultCommitMode: "never",
    defaultRunLabel: "run-2",
    defaultTags: ["tag-b"],
    rememberCommitChoice: true,
  });

  assert.equal(detached.notebookPath, null);
  assert.equal(detached.selectedCommitMode, "never");
  assert.equal(detached.rememberCommitChoice, true);
  assert.equal(detached.statusMessage, null);
  assert.equal(detached.auth.status, "authenticated");
  assert.deepEqual(detached.userMetadata.tags, ["tag-b"]);
});

void test("buildLoadedViewState preserves drafts for the same notebook", () => {
  const current = createInitialViewState();
  current.notebookPath = "analysis/notebook.ipynb";
  current.tagsInput = "draft-tag";
  current.userMetadata = {
    experiment_context: "legacy-value",
    extra_fields: {},
    notes: "draft notes",
    run_label: "draft-run",
    tags: ["draft-tag"],
  };
  current.statusKind = "info";
  current.statusMessage = "draft status";

  const loaded = buildLoadedViewState({
    activeCell: {
      cellId: "cell-1",
      isTrigger: true,
    },
    current,
    metadata: DEFAULT_METADATA,
    notebookPath: "analysis/notebook.ipynb",
    preferences: {
      defaultCommitMode: "always",
      defaultRunLabel: "pref-run",
      defaultTags: ["pref-tag"],
      rememberCommitChoice: false,
    },
    state: {
      auth: {
        pendingRequestId: null,
        status: "authenticated",
        storedNotebookNames: [],
        storedUserEmail: null,
        userEmail: "user@example.com",
      },
      effectiveConfig: null,
      notebookMetadata: null,
      repo: null,
      repoConfigPath: null,
      repoConfigLoaded: false,
    },
  });

  assert.equal(loaded.activeCellId, "cell-1");
  assert.equal(loaded.activeCellIsTrigger, true);
  assert.equal(loaded.tagsInput, "draft-tag");
  assert.equal(loaded.userMetadata.notes, "draft notes");
  assert.equal(loaded.userMetadata.run_label, "draft-run");
  assert.equal(loaded.userMetadata.experiment_context, null);
  assert.equal(loaded.statusMessage, "draft status");
});
