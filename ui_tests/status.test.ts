import assert from "node:assert/strict";
import test from "node:test";

import {
  error,
  info,
  statusForJobState,
  success,
  warning,
} from "../src/application/panel/status";

// --- the four visual kinds (C-PANEL-10) ---

void test("status constructors carry their kind and message", () => {
  assert.deepEqual(info("working"), { kind: "info", message: "working" });
  assert.deepEqual(success("done"), { kind: "success", message: "done" });
  assert.deepEqual(warning("careful"), { kind: "warning", message: "careful" });
  assert.deepEqual(error("broken"), { kind: "error", message: "broken" });
});

// --- delivery state maps to a visual kind (C-PANEL-10, C-SNAP-04/05/06) ---

void test("terminal delivery states map to success/error/warning", () => {
  assert.equal(statusForJobState("persisted", "Snapshot saved.").kind, "success");
  assert.equal(
    statusForJobState("failed", "Unable to save the snapshot.").kind,
    "error",
  );
  assert.equal(statusForJobState("abandoned", "Abandoned.").kind, "warning");
});

void test("in-progress delivery states are informational", () => {
  assert.equal(statusForJobState("queued", "Queued.").kind, "info");
  assert.equal(statusForJobState("running", "Saving…").kind, "info");
});

void test("statusForJobState carries the display message verbatim", () => {
  assert.equal(
    statusForJobState("persisted", "Snapshot saved. Job job-1.").message,
    "Snapshot saved. Job job-1.",
  );
});
