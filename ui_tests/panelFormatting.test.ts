import assert from "node:assert/strict";
import test from "node:test";

import {
  NOTEBOOK_UPLOAD_WARNING,
  describeBoolean,
  describeCommitMode,
  describeTriggerMode,
  formatSnapshotSubmissionStatus,
  formatStringList,
  formatTemplateValues,
} from "../src/panelFormatting";

void test("panel formatting helpers describe effective config values", () => {
  assert.equal(describeCommitMode("always"), "Always commit");
  assert.equal(describeCommitMode("never"), "Never commit");
  assert.equal(describeCommitMode("prompt"), "Prompt before commit");
  assert.equal(describeTriggerMode(true), "Every executed cell");
  assert.equal(describeTriggerMode(false), "Marked trigger cells");
  assert.equal(describeBoolean(true), "Yes");
  assert.equal(describeBoolean(false), "No");
});

void test("formatSnapshotSubmissionStatus reflects completed inline persistence", () => {
  const accepted = formatSnapshotSubmissionStatus({
    commitCreated: true,
    commitHash: "abcdef1234567890",
    commitUrl: "https://git.example.test/commit/abcdef1234567890",
    jobId: "job-42",
    labarchivesDirectoryName: "2026-04-10T15-00-00.000_snapshot-1",
    labarchivesMetaPageId: "page-1",
    labarchivesMetaPageName: "00 Metadata",
    labarchivesPageCount: 3,
    labarchivesPageId: "page-1",
    labarchivesPageName: "00 Metadata",
    queuePosition: 0,
    snapshotId: "snapshot-1",
    status: "accepted",
  });
  assert.ok(
    !accepted.toLowerCase().includes("queued"),
    `accepted status should not say 'queued': ${accepted}`,
  );
  assert.ok(
    accepted.toLowerCase().includes("saved"),
    `accepted status should say 'saved': ${accepted}`,
  );
  assert.ok(
    accepted.includes("job-42"),
    `accepted status should surface the job id: ${accepted}`,
  );
  assert.ok(
    accepted.includes("snapshot-1"),
    `accepted status should surface the snapshot id: ${accepted}`,
  );
  assert.ok(
    accepted.includes("abcdef123456"),
    `accepted status should surface a short commit hash: ${accepted}`,
  );
  assert.ok(
    accepted.includes("2026-04-10T15-00-00.000_snapshot-1"),
    `accepted status should surface the LabArchives directory: ${accepted}`,
  );
  assert.ok(
    accepted.includes("3 pages"),
    `accepted status should surface the LabArchives page count: ${accepted}`,
  );
  assert.ok(
    accepted.includes("00 Metadata"),
    `accepted status should surface the metadata page: ${accepted}`,
  );

  const rejected = formatSnapshotSubmissionStatus({
    message: "Connect LabArchives first.",
    reasonCode: "authentication_required",
    status: "rejected",
  });
  assert.ok(
    rejected.toLowerCase().includes("rejected"),
    `rejected status should explain itself: ${rejected}`,
  );
  assert.ok(rejected.includes("Connect LabArchives first."));
});

void test("formatSnapshotSubmissionStatus falls back to metadata page id", () => {
  const accepted = formatSnapshotSubmissionStatus({
    commitCreated: false,
    commitHash: null,
    commitUrl: null,
    jobId: "job-42",
    labarchivesDirectoryName: "2026-04-10T15-00-00.000_snapshot-1",
    labarchivesMetaPageId: "meta-page-1",
    labarchivesMetaPageName: null,
    labarchivesPageCount: 3,
    labarchivesPageId: null,
    labarchivesPageName: null,
    queuePosition: 0,
    snapshotId: null,
    status: "accepted",
  });

  assert.ok(
    accepted.includes("Metadata page meta-page-1."),
    `accepted status should surface the metadata page id: ${accepted}`,
  );
});

void test("NOTEBOOK_UPLOAD_WARNING informs users that outputs are uploaded", () => {
  const lowered = NOTEBOOK_UPLOAD_WARNING.toLowerCase();
  assert.ok(
    lowered.includes("output"),
    `expected warning to mention outputs: ${NOTEBOOK_UPLOAD_WARNING}`,
  );
  assert.ok(
    lowered.includes("upload"),
    `expected warning to mention upload: ${NOTEBOOK_UPLOAD_WARNING}`,
  );
});

void test("panel formatting helpers render empty and populated collections", () => {
  assert.equal(formatStringList([]), "(none)");
  assert.equal(
    formatStringList(["outputs", "reports/latest.csv"]),
    "outputs, reports/latest.csv",
  );
  assert.equal(formatTemplateValues({}), "(none)");
  assert.equal(
    formatTemplateValues({ project: "baseline-study", owner: "alice" }),
    "owner=alice, project=baseline-study",
  );
});
