import assert from "node:assert/strict";
import test from "node:test";

import {
  SnapshotPanelController,
  getSnapshotBlockedMessage,
  isSnapshotActionEnabled,
  snapshotErrorDetails,
  type PanelApi,
} from "../src/panel/controller";
import {
  parseSnapshotJobsResponse,
  parseSnapshotPreviewResponse,
  parseSnapshotSubmissionResult,
  type AuthState,
  type SnapshotJobsResponse,
  type SnapshotPreviewResponse,
  type SnapshotSubmissionResult,
} from "../src/types";

class Deferred<T> {
  readonly promise: Promise<T>;
  private resolveValue: ((value: T) => void) | null = null;

  constructor() {
    this.promise = new Promise<T>((resolve) => {
      this.resolveValue = resolve;
    });
  }

  resolve(value: T): void {
    assert.ok(this.resolveValue !== null);
    this.resolveValue(value);
  }
}

class FakeApi implements PanelApi {
  authResponses: (Promise<AuthState> | AuthState)[] = [];
  jobResponses: SnapshotJobsResponse[] = [];
  startAuthDeferred: Deferred<{
    authUrl: string | null;
    message: string;
    requestId: string | null;
    status: string;
  }> | null = null;
  readonly submitted: unknown[] = [];
  startAuthCalls = 0;
  signOutCalls = 0;
  listJobsCalls = 0;
  signOutError: Error | null = null;
  listJobsError: Error | null = null;
  previewError: Error | null = null;

  submitSnapshot(body: unknown): Promise<SnapshotSubmissionResult> {
    this.submitted.push(body);
    return Promise.resolve({
      message: "rejected",
      reasonCode: "test_rejected",
      status: "rejected",
    });
  }

  previewSnapshot(): Promise<SnapshotPreviewResponse> {
    if (this.previewError !== null) {
      return Promise.reject(this.previewError);
    }
    return Promise.resolve(previewResponse());
  }

  listJobs(): Promise<SnapshotJobsResponse> {
    this.listJobsCalls += 1;
    if (this.listJobsError !== null) {
      return Promise.reject(this.listJobsError);
    }
    return Promise.resolve(
      this.jobResponses.shift() ?? jobsResponse({ jobs: [] }),
    );
  }

  async authStatus(): Promise<AuthState> {
    const response = this.authResponses.shift();
    if (response === undefined) {
      return {
        pendingRequestId: null,
        status: "unauthenticated",
        storedNotebookNames: [],
        storedUserEmail: null,
        userEmail: null,
      };
    }
    return await response;
  }

  async startAuth(): Promise<{
    authUrl: string | null;
    message: string;
    requestId: string | null;
    status: string;
  }> {
    this.startAuthCalls += 1;
    if (this.startAuthDeferred !== null) {
      return await this.startAuthDeferred.promise;
    }
    return {
      authUrl: null,
      message: "Open the LabArchives authentication page to continue.",
      requestId: "request-1",
      status: "pending",
    };
  }

  signOut(): Promise<void> {
    this.signOutCalls += 1;
    if (this.signOutError !== null) {
      return Promise.reject(this.signOutError);
    }
    return Promise.resolve();
  }
}

function jobsResponse(raw: unknown): SnapshotJobsResponse {
  return parseSnapshotJobsResponse(raw);
}

function previewResponse(): SnapshotPreviewResponse {
  return parseSnapshotPreviewResponse({
    artifacts: [],
    generatedAt: "2026-05-26T12:00:00+00:00",
    provenance: {},
    runLabel: null,
    source: "frontend",
    tags: [],
    target: {
      notebookName: "Jupyter Snapshots",
      rootPath: "Notebook Log",
    },
  });
}

void test("snapshot action is disabled when no notebook is active", async () => {
  const api = new FakeApi();
  api.authResponses.push({
    pendingRequestId: null,
    status: "authenticated",
    storedNotebookNames: [],
    storedUserEmail: null,
    userEmail: "user@example.com",
  });
  const controller = new SnapshotPanelController(api, { pollIntervalMs: 0 });
  await controller.refreshAuth();

  assert.equal(isSnapshotActionEnabled(controller.state.get()), false);
  assert.equal(
    getSnapshotBlockedMessage(controller.state.get()),
    "Open a notebook before creating a snapshot.",
  );
  controller.dispose();
});

void test("manual snapshots are not throttled by another in-flight submission", async () => {
  const api = new FakeApi();
  const controller = new SnapshotPanelController(api, { pollIntervalMs: 0 });
  controller.setNotebookName("nb.ipynb");

  const first = controller.snapshot({ id: 1 });
  const second = controller.snapshot({ id: 2 });
  await Promise.all([first, second]);

  assert.deepEqual(api.submitted, [{ id: 1 }, { id: 2 }]);
  controller.dispose();
});

void test("snapshot request options resolve ask commit choices and metadata", () => {
  const api = new FakeApi();
  const controller = new SnapshotPanelController(api, { pollIntervalMs: 0 });

  controller.updateSnapshotOptions({
    commitDecision: "always",
    metadataFields: "operator=Ada\ninvalid\nsample = 42",
    notes: "operator note",
    rememberCommitChoice: true,
    runLabel: " training-3 ",
    tags: "baseline, gpu, baseline",
  });

  assert.deepEqual(controller.snapshotRequestOptions(), {
    commitMode: "always",
    extraFields: { operator: "Ada", sample: "42" },
    notes: "operator note",
    rememberCommitChoice: true,
    runLabel: "training-3",
    runLabelEdited: true,
    tags: ["baseline", "gpu"],
  });
  controller.dispose();
});

void test("directive defaults prefill run label and tags until edited", () => {
  const api = new FakeApi();
  const controller = new SnapshotPanelController(api, { pollIntervalMs: 0 });

  controller.setDirectiveDefaults({ runLabel: "directive-run", tags: ["gpu"] });
  assert.equal(controller.state.get().snapshotOptions.runLabel, "directive-run");
  assert.equal(controller.state.get().snapshotOptions.tags, "gpu");
  assert.equal(controller.snapshotRequestOptions().runLabelEdited, false);

  controller.updateSnapshotOptions({ runLabel: "manual-run" });
  controller.setDirectiveDefaults({ runLabel: "new-directive", tags: ["baseline"] });
  assert.equal(controller.state.get().snapshotOptions.runLabel, "manual-run");
  assert.equal(controller.state.get().snapshotOptions.tags, "baseline");
  assert.equal(controller.snapshotRequestOptions().runLabelEdited, true);
  controller.dispose();
});

void test("auth notebook names populate target options", async () => {
  const api = new FakeApi();
  api.authResponses.push({
    pendingRequestId: null,
    status: "authenticated",
    storedNotebookNames: ["Team Notebook", "Personal Notebook"],
    storedUserEmail: null,
    userEmail: "user@example.com",
  });
  const controller = new SnapshotPanelController(api, { pollIntervalMs: 0 });

  await controller.refreshAuth();

  assert.deepEqual(controller.state.get().targetOptions.availableNotebookNames, [
    "Team Notebook",
    "Personal Notebook",
  ]);
  controller.dispose();
});

void test("accepted snapshots poll activity until the job reaches a terminal state", async () => {
  const api = new FakeApi();
  api.submitSnapshot = (body: unknown): Promise<SnapshotSubmissionResult> => {
    api.submitted.push(body);
    return Promise.resolve(
      parseSnapshotSubmissionResult({
        jobId: "job-1",
        queuePosition: 1,
        status: "accepted",
      }),
    );
  };
  api.jobResponses.push(
    jobsResponse({
      jobs: [
        {
          displayMessage: "Snapshot queued.",
          jobId: "job-1",
          notebookPath: "nb.ipynb",
          runOutcome: "n/a",
          source: "manual",
          state: "queued",
          submittedAt: "2026-05-26T12:00:00+00:00",
        },
      ],
    }),
    jobsResponse({
      jobs: [
        {
          displayMessage:
            "Saving notebook, creating snapshot artifacts, and uploading to LabArchives.",
          jobId: "job-1",
          notebookPath: "nb.ipynb",
          runOutcome: "n/a",
          source: "manual",
          state: "running",
          submittedAt: "2026-05-26T12:00:00+00:00",
        },
      ],
    }),
    jobsResponse({
      jobs: [
        {
          directoryUrl: "https://labarchives.test/dir-1",
          displayMessage: "Snapshot saved. Job job-1.",
          jobId: "job-1",
          notebookPath: "nb.ipynb",
          runOutcome: "n/a",
          source: "manual",
          state: "persisted",
          submittedAt: "2026-05-26T12:00:00+00:00",
        },
      ],
    }),
  );
  const controller = new SnapshotPanelController(api, { pollIntervalMs: 0 });

  await controller.snapshot({ id: 1 });

  assert.equal(api.listJobsCalls, 3);
  assert.equal(
    controller.state.get().activity.rows[0]?.message,
    "Snapshot saved. Job job-1.",
  );
  assert.deepEqual(controller.state.get().status, {
    kind: "success",
    message: "Snapshot saved. Job job-1.",
  });
  controller.dispose();
});

void test("coalesced accepted snapshots poll the existing job", async () => {
  const api = new FakeApi();
  api.submitSnapshot = (body: unknown): Promise<SnapshotSubmissionResult> => {
    api.submitted.push(body);
    return Promise.resolve(
      parseSnapshotSubmissionResult({
        coalescedInto: "job-1",
        jobId: "job-2",
        status: "accepted",
      }),
    );
  };
  api.jobResponses.push(
    jobsResponse({
      jobs: [
        {
          displayMessage: "Snapshot saved. Job job-1.",
          jobId: "job-1",
          notebookPath: "nb.ipynb",
          runOutcome: "success",
          source: "trigger_cell",
          state: "persisted",
          submittedAt: "2026-05-26T12:00:00+00:00",
        },
      ],
    }),
  );
  const controller = new SnapshotPanelController(api, { pollIntervalMs: 0 });

  await controller.snapshot({ id: 1 });

  assert.equal(controller.state.get().activity.rows[0]?.jobId, "job-1");
  assert.deepEqual(controller.state.get().status, {
    kind: "success",
    message: "Snapshot saved. Job job-1.",
  });
  controller.dispose();
});

void test("session-expired snapshot failures refresh auth state", async () => {
  const api = new FakeApi();
  api.submitSnapshot = (body: unknown): Promise<SnapshotSubmissionResult> => {
    api.submitted.push(body);
    return Promise.resolve(
      parseSnapshotSubmissionResult({
        jobId: "job-1",
        status: "accepted",
      }),
    );
  };
  api.jobResponses.push(
    jobsResponse({
      jobs: [
        {
          displayMessage:
            "LabArchives session expired; sign in again to continue.",
          errorCode: "labarchives_session_expired",
          errorMessage: "LabArchives session expired; sign in again to continue.",
          jobId: "job-1",
          notebookPath: "nb.ipynb",
          runOutcome: "n/a",
          source: "manual",
          state: "failed",
          submittedAt: "2026-05-26T12:00:00+00:00",
        },
      ],
    }),
  );
  api.authResponses.push({
    pendingRequestId: null,
    status: "unauthenticated",
    storedNotebookNames: [],
    storedUserEmail: "user@example.com",
    userEmail: null,
  });
  const controller = new SnapshotPanelController(api, { pollIntervalMs: 0 });

  await controller.snapshot({ id: 1 });

  assert.equal(
    controller.state.get().readiness.authDescription,
    "Not authenticated. Previously connected as user@example.com.",
  );
  controller.dispose();
});

void test("snapshot error details are visible from the top snapshot state", async () => {
  const api = new FakeApi();
  api.submitSnapshot = (body: unknown): Promise<SnapshotSubmissionResult> => {
    api.submitted.push(body);
    return Promise.resolve(
      parseSnapshotSubmissionResult({
        jobId: "job-1",
        status: "accepted",
      }),
    );
  };
  api.jobResponses.push(
    jobsResponse({
      jobs: [
        {
          displayMessage: "Unable to save the snapshot.",
          errorCode: "watched_file_artifact_read_failed",
          errorMessage: "Could not read tracked file outputs/result.csv.",
          jobId: "job-1",
          notebookPath: "nb.ipynb",
          runOutcome: "n/a",
          source: "manual",
          state: "failed",
          submittedAt: "2026-05-26T12:00:00+00:00",
        },
      ],
    }),
  );
  const controller = new SnapshotPanelController(api, { pollIntervalMs: 0 });

  await controller.snapshot({ id: 1 });

  assert.deepEqual(snapshotErrorDetails(controller.state.get()), [
    "Full error: Could not read tracked file outputs/result.csv.",
    "Error code: watched_file_artifact_read_failed",
  ]);
  controller.dispose();
});

void test("accepted snapshots do not report save failure when final status refresh fails", async () => {
  const api = new FakeApi();
  api.submitSnapshot = (body: unknown): Promise<SnapshotSubmissionResult> => {
    api.submitted.push(body);
    return Promise.resolve(
      parseSnapshotSubmissionResult({
        jobId: "job-1",
        queuePosition: 1,
        status: "accepted",
      }),
    );
  };
  api.listJobsError = new Error("activity endpoint unavailable");
  const controller = new SnapshotPanelController(api, { pollIntervalMs: 0 });

  await controller.snapshot({ id: 1 });

  assert.equal(api.listJobsCalls, 1);
  assert.deepEqual(controller.state.get().status, {
    kind: "warning",
    message:
      "Snapshot request was accepted, but the final status could not be refreshed.",
  });
  controller.dispose();
});

void test("preview refresh failures do not overwrite an active snapshot status", async () => {
  const api = new FakeApi();
  const submit = new Deferred<SnapshotSubmissionResult>();
  api.submitSnapshot = (body: unknown): Promise<SnapshotSubmissionResult> => {
    api.submitted.push(body);
    return submit.promise;
  };
  api.previewError = new Error("preview parse failed");
  const controller = new SnapshotPanelController(api, { pollIntervalMs: 0 });

  const snapshot = controller.snapshot({ id: 1 });
  await Promise.resolve();
  await controller.refreshPreview({ id: 1 });

  assert.deepEqual(controller.state.get().status, {
    kind: "info",
    message:
      "Saving notebook, creating snapshot artifacts, and uploading to LabArchives.",
  });

  submit.resolve({
    message: "rejected after test preview race",
    reasonCode: "test_rejected",
    status: "rejected",
  });
  await snapshot;
  controller.dispose();
});

void test("auth actions are guarded while a start request is in flight", async () => {
  const api = new FakeApi();
  api.startAuthDeferred = new Deferred();
  const controller = new SnapshotPanelController(api, { pollIntervalMs: 0 });

  const first = controller.toggleAuth();
  const second = controller.toggleAuth();
  assert.equal(api.startAuthCalls, 1);
  assert.equal(controller.state.get().authBusy, true);

  api.startAuthDeferred.resolve({
    authUrl: null,
    message: "Open the LabArchives authentication page to continue.",
    requestId: "request-1",
    status: "pending",
  });
  await Promise.all([first, second]);

  assert.equal(controller.state.get().authBusy, false);
  controller.dispose();
});

void test("pending auth auto-cancels after the timeout", async () => {
  const api = new FakeApi();
  api.authResponses.push(
    {
      pendingRequestId: "request-1",
      status: "pending",
      storedNotebookNames: [],
      storedUserEmail: "user@example.com",
      userEmail: null,
    },
    {
      pendingRequestId: null,
      status: "unauthenticated",
      storedNotebookNames: [],
      storedUserEmail: "user@example.com",
      userEmail: null,
    },
  );
  const controller = new SnapshotPanelController(api, {
    authPendingTimeoutMs: 0,
    pollIntervalMs: 0,
  });

  await controller.refreshAuth();
  await new Promise((resolve) => {
    setTimeout(resolve, 5);
  });

  assert.equal(
    controller.state.get().readiness.authDescription,
    "Not authenticated. Previously connected as user@example.com.",
  );
  assert.deepEqual(controller.state.get().status, {
    kind: "warning",
    message: "Authentication pending timed out. Click Connect to try again.",
  });
  controller.dispose();
});

void test("sign out shows contract status messages and refreshes auth", async () => {
  const api = new FakeApi();
  const signOutStarted = new Deferred<void>();
  const signOutMayFinish = new Deferred<void>();
  api.authResponses.push(
    {
      pendingRequestId: null,
      status: "authenticated",
      storedNotebookNames: [],
      storedUserEmail: null,
      userEmail: "user@example.com",
    },
    {
      pendingRequestId: null,
      status: "unauthenticated",
      storedNotebookNames: [],
      storedUserEmail: null,
      userEmail: null,
    },
  );
  api.signOut = (): Promise<void> => {
    api.signOutCalls += 1;
    signOutStarted.resolve(undefined);
    return signOutMayFinish.promise;
  };
  const controller = new SnapshotPanelController(api, { pollIntervalMs: 0 });
  await controller.refreshAuth();

  const pending = controller.toggleAuth();
  await signOutStarted.promise;
  assert.deepEqual(controller.state.get().status, {
    kind: "info",
    message: "Signing out...",
  });
  signOutMayFinish.resolve(undefined);
  await pending;

  assert.equal(api.signOutCalls, 1);
  assert.deepEqual(controller.state.get().status, {
    kind: "info",
    message: "Signed out of LabArchives.",
  });
  assert.equal(controller.state.get().readiness.authDescription, "Not authenticated.");
  controller.dispose();
});

void test("sign out failures use the contract error message", async () => {
  const api = new FakeApi();
  api.authResponses.push({
    pendingRequestId: null,
    status: "authenticated",
    storedNotebookNames: [],
    storedUserEmail: null,
    userEmail: "user@example.com",
  });
  api.signOutError = new Error("low-level delete failed");
  const controller = new SnapshotPanelController(api, { pollIntervalMs: 0 });
  await controller.refreshAuth();

  await controller.toggleAuth();

  assert.deepEqual(controller.state.get().status, {
    kind: "error",
    message: "Unable to sign out of LabArchives.",
  });
  controller.dispose();
});

void test("out-of-order auth refreshes keep the newest response", async () => {
  const api = new FakeApi();
  const first = new Deferred<AuthState>();
  const second = new Deferred<AuthState>();
  api.authResponses.push(first.promise, second.promise);
  const controller = new SnapshotPanelController(api, { pollIntervalMs: 0 });

  const firstRefresh = controller.refreshAuth();
  const secondRefresh = controller.refreshAuth();
  second.resolve({
    pendingRequestId: null,
    status: "authenticated",
    storedNotebookNames: [],
    storedUserEmail: null,
    userEmail: "user@example.com",
  });
  await secondRefresh;
  first.resolve({
    pendingRequestId: null,
    status: "unauthenticated",
    storedNotebookNames: [],
    storedUserEmail: null,
    userEmail: null,
  });
  await firstRefresh;

  assert.equal(
    controller.state.get().readiness.authDescription,
    "Authenticated as user@example.com.",
  );
  controller.dispose();
});
