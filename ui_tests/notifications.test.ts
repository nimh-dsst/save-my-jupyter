import assert from "node:assert/strict";
import test from "node:test";

import {
  TRIGGER_FAILURE_AUTO_CLOSE_MS,
  TRIGGER_FAILURE_NOTIFICATION,
  TRIGGER_SUCCESS_AUTO_CLOSE_MS,
  TRIGGER_SUCCESS_NOTIFICATION,
  triggerSnapshotNotification,
} from "../src/application/feedback/notifications";

void test("trigger snapshot feedback does not toast normal progress or duplicate skips", () => {
  assert.equal(triggerSnapshotNotification(null), null);
  assert.equal(
    triggerSnapshotNotification({ kind: "info", message: "Saving..." }),
    null,
  );
  assert.equal(
    triggerSnapshotNotification({
      kind: "warning",
      message: "A snapshot already exists for this run.",
    }),
    null,
  );
});

void test("trigger snapshot feedback uses a compact success toast", () => {
  assert.deepEqual(
    triggerSnapshotNotification({
      kind: "success",
      message:
        "Snapshot saved. Job abc. Commit URL: https://example.test/long.",
    }),
    {
      autoClose: 1000,
      kind: "success",
      message: TRIGGER_SUCCESS_NOTIFICATION,
    },
  );
  assert.equal(TRIGGER_SUCCESS_AUTO_CLOSE_MS, 1000);
});

void test("trigger snapshot feedback uses a compact error toast", () => {
  assert.deepEqual(
    triggerSnapshotNotification({
      kind: "error",
      message:
        "Unable to save the snapshot. Job abc. Commit URL: https://example.test/long.",
    }),
    {
      autoClose: TRIGGER_FAILURE_AUTO_CLOSE_MS,
      kind: "error",
      message: TRIGGER_FAILURE_NOTIFICATION,
    },
  );
});
