import assert from "node:assert/strict";
import test from "node:test";

import { buildActivitySection } from "../src/application/panel/activity";
import { buildReadinessSection } from "../src/application/panel/readiness";
import { parseAuthState, parseSnapshotJobsResponse } from "../src/types";

// --- readiness (C-AUTH-03, C-SNAP-02) ---

void test("authenticated readiness allows snapshots and offers sign out", () => {
  const section = buildReadinessSection(
    parseAuthState({ status: "authenticated", userEmail: "a@b.org" }),
  );
  assert.equal(section.canSnapshot, true);
  assert.equal(section.authDescription, "Authenticated as a@b.org.");
  assert.equal(section.authButtonLabel, "Sign out");
  assert.equal(section.blockedMessage, null);
});

void test("unauthenticated readiness blocks and offers connect", () => {
  const section = buildReadinessSection(
    parseAuthState({ status: "unauthenticated" }),
  );
  assert.equal(section.canSnapshot, false);
  assert.equal(section.authDescription, "Not authenticated.");
  assert.equal(section.authButtonLabel, "Connect");
  assert.equal(
    section.blockedMessage,
    "Connect LabArchives before creating a snapshot.",
  );
});

void test("prior connection is surfaced when signed out", () => {
  const section = buildReadinessSection(
    parseAuthState({ status: "unauthenticated", storedUserEmail: "old@b.org" }),
  );
  assert.equal(
    section.authDescription,
    "Not authenticated. Previously connected as old@b.org.",
  );
});

void test("pending auth shows the pending phrasing", () => {
  const section = buildReadinessSection(parseAuthState({ status: "pending" }));
  assert.equal(section.authDescription, "Authentication pending.");
});

// --- activity (C-DEST-05) ---

void test("empty activity shows an empty-state message", () => {
  const section = buildActivitySection(parseSnapshotJobsResponse({ jobs: [] }));
  assert.equal(section.rows.length, 0);
  assert.ok(section.emptyMessage !== null);
});

void test("activity rows carry status, message, and the clickable url", () => {
  const section = buildActivitySection(
    parseSnapshotJobsResponse({
      jobs: [
        {
          jobId: "job-1",
          submittedAt: "2026-05-26T12:00:00+00:00",
          source: "manual",
          notebookPath: "nb.ipynb",
          state: "persisted",
          runOutcome: "success",
          displayMessage: "Snapshot saved.",
          directoryUrl: "https://labarchives.test/dir-1",
        },
      ],
    }),
  );
  const [row] = section.rows;
  assert.ok(row);
  assert.equal(row.statusLabel, "Saved");
  assert.equal(row.message, "Snapshot saved.");
  assert.equal(row.url, "https://labarchives.test/dir-1");
  assert.equal(row.isError, false);
  assert.deepEqual(row.phaseLabels, []);
});

void test("failed activity rows expose backend error details", () => {
  const section = buildActivitySection(
    parseSnapshotJobsResponse({
      jobs: [
        {
          displayMessage: "Unable to save the snapshot.",
          errorCode: "watched_file_artifact_read_failed",
          errorMessage: "Could not read tracked file outputs/result.csv.",
          jobId: "job-1",
          notebookPath: "nb.ipynb",
          runOutcome: "n/a",
          source: "trigger_cell",
          state: "failed",
          submittedAt: "2026-05-26T12:00:00+00:00",
        },
      ],
    }),
  );

  const [row] = section.rows;
  assert.ok(row);
  assert.equal(row.isError, true);
  assert.deepEqual(row.errorDetails, [
    "Full error: Could not read tracked file outputs/result.csv.",
    "Error code: watched_file_artifact_read_failed",
  ]);
  assert.deepEqual(section.latestFailureDetails, row.errorDetails);
});

void test("running activity rows expose phase-level progress labels", () => {
  const section = buildActivitySection(
    parseSnapshotJobsResponse({
      jobs: [
        {
          jobId: "job-1",
          submittedAt: "2026-05-26T12:00:00+00:00",
          source: "manual",
          notebookPath: "nb.ipynb",
          state: "running",
          runOutcome: "n/a",
          displayMessage:
            "Saving notebook, creating snapshot artifacts, and uploading to LabArchives.",
        },
      ],
    }),
  );

  assert.deepEqual(section.rows[0]?.phaseLabels, [
    "Saving notebook",
    "Capturing artifacts",
    "Committing changes",
    "Uploading to LabArchives",
  ]);
  const [row] = section.rows;
  assert.ok(row);
  assert.deepEqual(row.phaseItems.map((phase) => phase.status), [
    "current",
    "current",
    "current",
    "current",
  ]);
});

void test("activity section only shows the most recent five rows", () => {
  const jobs = Array.from({ length: 7 }, (_value, index) => ({
    displayMessage: `Snapshot ${String(index)}`,
    jobId: `job-${String(index)}`,
    notebookPath: "nb.ipynb",
    runOutcome: "success",
    source: "manual",
    state: "persisted",
    submittedAt: "2026-05-26T12:00:00+00:00",
  }));

  const section = buildActivitySection(parseSnapshotJobsResponse({ jobs }));

  assert.equal(section.rows.length, 5);
  assert.equal(section.totalRows, 7);
  assert.equal(section.overflowMessage, "Showing 5 most recent of 7 runs.");
  assert.deepEqual(
    section.rows.map((row) => row.jobId),
    ["job-0", "job-1", "job-2", "job-3", "job-4"],
  );
});

void test("an errored run is recorded without marking a persisted snapshot failed", () => {
  const section = buildActivitySection(
    parseSnapshotJobsResponse({
      jobs: [
        {
          jobId: "job-2",
          submittedAt: "2026-05-26T12:00:00+00:00",
          source: "trigger_cell",
          notebookPath: "nb.ipynb",
          state: "persisted",
          runOutcome: "error",
          displayMessage: "Snapshot saved.",
        },
      ],
    }),
  );
  const [row] = section.rows;
  assert.ok(row);
  assert.equal(row.statusLabel, "Saved");
  assert.equal(row.runOutcomeLabel, "Run ended with errors");
  assert.equal(row.isError, false);
});
