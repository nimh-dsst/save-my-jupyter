import assert from "node:assert/strict";
import test from "node:test";

import {
  getSnapshotAvailability,
  requiresPanelSetup
} from "../src/panelBehavior";

void test("requiresPanelSetup blocks unauthenticated states", () => {
  assert.equal(
    requiresPanelSetup({
      pendingRequestId: null,
      status: "unauthenticated",
      storedNotebookNames: [],
      storedUserEmail: null,
      userEmail: null
    }),
    true
  );
  assert.equal(
    requiresPanelSetup({
      pendingRequestId: "pending-request",
      status: "pending",
      storedNotebookNames: [],
      storedUserEmail: null,
      userEmail: null
    }),
    true
  );
});

void test("requiresPanelSetup allows authenticated state", () => {
  assert.equal(
    requiresPanelSetup({
      pendingRequestId: null,
      status: "authenticated",
      storedNotebookNames: [],
      storedUserEmail: null,
      userEmail: "user@example.com"
    }),
    false
  );
});

void test("getSnapshotAvailability explains disabled states", () => {
  assert.deepEqual(
    getSnapshotAvailability(
      {
        pendingRequestId: null,
        status: "unauthenticated",
        storedNotebookNames: [],
        storedUserEmail: null,
        userEmail: null
      },
      "analysis/notebook.ipynb",
      false
    ),
    {
      enabled: false,
      message: "Connect LabArchives to enable snapshot creation."
    }
  );
  assert.deepEqual(
    getSnapshotAvailability(
      {
        pendingRequestId: null,
        status: "authenticated",
        storedNotebookNames: [],
        storedUserEmail: null,
        userEmail: "user@example.com"
      },
      null,
      false
    ),
    {
      enabled: false,
      message: "Open a notebook to configure and create snapshots."
    }
  );
  assert.deepEqual(
    getSnapshotAvailability(
      {
        pendingRequestId: null,
        status: "authenticated",
        storedNotebookNames: [],
        storedUserEmail: null,
        userEmail: "user@example.com"
      },
      "analysis/notebook.ipynb",
      true
    ),
    {
      enabled: false,
      message: "Save My Jupyter is working on the current request."
    }
  );
});

void test("getSnapshotAvailability allows ready snapshots", () => {
  assert.deepEqual(
    getSnapshotAvailability(
      {
        pendingRequestId: null,
        status: "authenticated",
        storedNotebookNames: [],
        storedUserEmail: null,
        userEmail: "user@example.com"
      },
      "analysis/notebook.ipynb",
      false
    ),
    {
      enabled: true,
      message: "Ready to create a snapshot for this notebook."
    }
  );
});
