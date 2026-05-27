import assert from "node:assert/strict";
import test from "node:test";

import { buildSnapshotRequestBody } from "../src/notebook/requestBuilders";

void test("manual request body uses snake_case keys the backend parses", () => {
  const body = buildSnapshotRequestBody({
    source: "manual",
    notebookPath: "analysis/nb.ipynb",
    notebookName: "nb.ipynb",
    documentId: "doc-1",
    tags: ["baseline"],
    runLabel: "run-1",
    watchedPaths: ["outputs"],
  });
  assert.equal(body["source"], "manual");
  const context = body["notebook_context"] as Record<string, unknown>;
  assert.equal(context["notebook_path"], "analysis/nb.ipynb");
  assert.equal(context["document_id"], "doc-1");
  const metadata = body["user_metadata"] as Record<string, unknown>;
  assert.deepEqual(metadata["tags"], ["baseline"]);
  assert.equal(metadata["run_label"], "run-1");
  assert.deepEqual(body["watched_paths"], ["outputs"]);
  assert.equal("commit_mode" in body, false);
  assert.equal("notebook_content" in body, false);
});

void test("trigger request body carries the triggering and triggered cells", () => {
  const body = buildSnapshotRequestBody({
    source: "trigger_cell",
    notebookPath: "nb.ipynb",
    notebookName: "nb.ipynb",
    triggeringCellId: "cell-1",
    triggeredCellIds: ["cell-1", "cell-2"],
    cellExecutionCount: 7,
    commitMode: "always",
    notebookContent: { cells: [] },
  });
  const context = body["notebook_context"] as Record<string, unknown>;
  assert.equal(context["triggering_cell_id"], "cell-1");
  assert.deepEqual(context["triggered_cell_ids"], ["cell-1", "cell-2"]);
  assert.equal(context["cell_execution_count"], 7);
  assert.equal(body["commit_mode"], "always");
  assert.deepEqual(body["notebook_content"], { cells: [] });
});
