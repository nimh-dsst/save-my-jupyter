import { ApiClientError } from "../apiClient";
import {
  buildActivitySection,
  type ActivitySection,
} from "../application/panel/activity";
import {
  buildReadinessSection,
  type ReadinessSection,
} from "../application/panel/readiness";
import {
  error as errorStatus,
  info,
  statusForJobState,
  warning,
  type PanelStatus,
} from "../application/panel/status";
import {
  buildWillBeSavedSection,
  type WillBeSavedSection,
} from "../application/panel/willBeSaved";
import type { TriggerCellState } from "../notebook/triggers";
import { DEFAULT_USER_PREFERENCES } from "../settings";
import { createSignal, patchSignal, type WritableSignal } from "../signals";
import {
  type AuthState,
  type AuthStartResponse,
  type CommitMode,
  type JobState,
  type SnapshotJobsResponse,
  type SnapshotPreviewResponse,
  type SnapshotSubmissionResult,
  type UserPreferences,
} from "../types";

/** The narrow backend surface the controller depends on, so the panel logic is
 * tested against a fake without a live server. ApiClient satisfies it. */
export interface PanelApi {
  submitSnapshot(body: unknown): Promise<SnapshotSubmissionResult>;
  previewSnapshot(body: unknown): Promise<SnapshotPreviewResponse>;
  listJobs(limit: number): Promise<SnapshotJobsResponse>;
  authStatus(): Promise<AuthState>;
  startAuth(): Promise<AuthStartResponse>;
  signOut(): Promise<void>;
}

export interface PanelState {
  readonly auth: AuthState;
  readonly readiness: ReadinessSection;
  readonly activity: ActivitySection;
  readonly willBeSaved: WillBeSavedSection | null;
  readonly notebookName: string | null;
  readonly watchedPaths: readonly string[];
  readonly triggerOptions: TriggerOptionsState;
  readonly snapshotOptions: SnapshotOptionsState;
  readonly targetOptions: TargetOptionsState;
  readonly status: PanelStatus | null;
  readonly busy: boolean;
  readonly authBusy: boolean;
}

export interface TriggerOptionsState {
  readonly activeCell: TriggerCellState;
  readonly allCellsTrigger: boolean;
}

export interface SnapshotOptionsState {
  readonly commitMode: CommitMode;
  readonly commitDecision: Exclude<CommitMode, "ask">;
  readonly rememberCommitChoice: boolean;
  readonly runLabel: string;
  readonly tags: string;
  readonly notes: string;
  readonly metadataFields: string;
  readonly runLabelEdited: boolean;
  readonly tagsEdited: boolean;
}

export interface TargetOptionsState {
  readonly notebookName: string;
  readonly rootPath: string;
  readonly availableNotebookNames: readonly string[];
}

export interface SnapshotRequestOptions {
  readonly commitMode: Exclude<CommitMode, "ask">;
  readonly rememberCommitChoice: boolean;
  readonly runLabel: string | null;
  readonly runLabelEdited: boolean;
  readonly tags: readonly string[];
  readonly notes: string | null;
  readonly extraFields: Record<string, string>;
}

export interface DirectiveDefaults {
  readonly runLabel: string | null;
  readonly tags: readonly string[];
}

export interface ControllerOptions {
  /** Delay between activity polls after an accepted snapshot; 0 in tests. */
  readonly pollIntervalMs?: number;
  /** Timeout for abandoned OAuth tabs; shorter in tests. */
  readonly authPendingTimeoutMs?: number;
}

const NO_NOTEBOOK_MESSAGE = "Open a notebook before creating a snapshot.";
const SAVING_MESSAGE =
  "Saving notebook, creating snapshot artifacts, and uploading to LabArchives.";
const STATUS_REFRESH_FAILED_MESSAGE =
  "Snapshot request was accepted, but the final status could not be refreshed.";
const PREVIEW_REFRESH_FAILED_MESSAGE = "Snapshot preview could not be refreshed.";
const ACTIVITY_LIMIT = 20;
const DEFAULT_POLL_INTERVAL_MS = 1500;
const MAX_POLLS = 600;
const PENDING_AUTH_TIMEOUT_MS = 60_000;
const PENDING_AUTH_EXPIRED_MESSAGE =
  "Authentication pending timed out. Click Connect to try again.";
const SESSION_EXPIRED_CODE = "labarchives_session_expired";

const UNAUTHENTICATED: AuthState = {
  pendingRequestId: null,
  status: "unauthenticated",
  storedNotebookNames: [],
  storedUserEmail: null,
  userEmail: null,
};

export function initialPanelState(): PanelState {
  return {
    auth: UNAUTHENTICATED,
    readiness: buildReadinessSection(UNAUTHENTICATED),
    activity: buildActivitySection({ jobs: [] }),
    willBeSaved: null,
    notebookName: null,
    watchedPaths: [],
    triggerOptions: {
      activeCell: "unknown",
      allCellsTrigger: false,
    },
    snapshotOptions: defaultSnapshotOptions(DEFAULT_USER_PREFERENCES),
    targetOptions: {
      notebookName: "",
      rootPath: "",
      availableNotebookNames: [],
    },
    status: null,
    busy: false,
    authBusy: false,
  };
}

/** The single reason a snapshot is blocked, highest priority first, or null when
 * the action is allowed (contracts C-PANEL-02, C-SNAP-02). */
export function getSnapshotBlockedMessage(state: PanelState): string | null {
  if (!state.readiness.canSnapshot) {
    return state.readiness.blockedMessage;
  }
  if (state.notebookName === null) {
    return NO_NOTEBOOK_MESSAGE;
  }
  return null;
}

export function isSnapshotActionEnabled(state: PanelState): boolean {
  return getSnapshotBlockedMessage(state) === null;
}

export function snapshotErrorDetails(state: PanelState): readonly string[] {
  if (state.status?.kind !== "error") {
    return [];
  }
  if (state.activity.latestFailureDetails.length > 0) {
    return state.activity.latestFailureDetails;
  }
  return [`Full error: ${state.status.message}`];
}

/** Owns the panel signal and drives it from the backend. Browser-only except for
 * the pure helpers above; verified by panelController.test.ts against a fake. */
export class SnapshotPanelController {
  readonly state: WritableSignal<PanelState> =
    createSignal(initialPanelState());

  private readonly pollIntervalMs: number;
  private readonly authPendingTimeoutMs: number;
  private authSeq = 0;
  private disposed = false;
  private channel: BroadcastChannel | null = null;
  private pendingAuthTimer: ReturnType<typeof setTimeout> | null = null;

  private readonly onStorage = (event: StorageEvent): void => {
    if (event.key === "save-my-jupyter-auth") {
      void this.refreshAuth();
    }
  };

  constructor(
    private readonly api: PanelApi,
    options: ControllerOptions = {},
  ) {
    this.pollIntervalMs = options.pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS;
    this.authPendingTimeoutMs =
      options.authPendingTimeoutMs ?? PENDING_AUTH_TIMEOUT_MS;
    // The OAuth callback tab signals completion; refresh auth when it does.
    try {
      this.channel = new BroadcastChannel("save-my-jupyter-auth");
      this.channel.onmessage = (): void => {
        void this.refreshAuth();
      };
    } catch {
      // BroadcastChannel unavailable; the storage event below still covers it.
      this.channel = null;
    }
    try {
      window.addEventListener("storage", this.onStorage);
    } catch {
      // No window (non-browser host); nothing to wire.
    }
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.clearPendingAuthTimer();
    if (this.channel !== null) {
      try {
        this.channel.close();
      } catch {
        // Already closed.
      }
      this.channel = null;
    }
    try {
      window.removeEventListener("storage", this.onStorage);
    } catch {
      // No window to detach from.
    }
  }

  setNotebookName(name: string | null): void {
    patchSignal(this.state, {
      notebookName: name,
      willBeSaved: name === null ? null : this.state.get().willBeSaved,
    });
  }

  setTriggerOptions(options: TriggerOptionsState): void {
    patchSignal(this.state, { triggerOptions: options });
  }

  setWatchedPaths(paths: readonly string[]): void {
    patchSignal(this.state, { watchedPaths: [...paths] });
  }

  setTargetOptions(options: Partial<Omit<TargetOptionsState, "availableNotebookNames">>): void {
    patchSignal(this.state, {
      targetOptions: { ...this.state.get().targetOptions, ...options },
    });
  }

  setPreferences(preferences: UserPreferences): void {
    const current = this.state.get().snapshotOptions;
    patchSignal(this.state, {
      snapshotOptions: {
        ...current,
        commitMode: preferences.defaultCommitMode,
        commitDecision:
          preferences.defaultCommitMode === "ask"
            ? current.commitDecision
            : preferences.defaultCommitMode,
        rememberCommitChoice: preferences.rememberCommitChoice,
        runLabel: current.runLabelEdited
          ? current.runLabel
          : (preferences.defaultRunLabel ?? ""),
        tags: current.tagsEdited
          ? current.tags
          : preferences.defaultTags.join(", "),
      },
    });
  }

  setDirectiveDefaults(defaults: DirectiveDefaults): void {
    const current = this.state.get().snapshotOptions;
    patchSignal(this.state, {
      snapshotOptions: {
        ...current,
        runLabel:
          current.runLabelEdited
            ? current.runLabel
            : (defaults.runLabel ?? current.runLabel),
        tags: current.tagsEdited ? current.tags : defaults.tags.join(", "),
      },
    });
  }

  updateSnapshotOptions(
    patch: Partial<
      Pick<
        SnapshotOptionsState,
        | "commitMode"
        | "commitDecision"
        | "rememberCommitChoice"
        | "runLabel"
        | "tags"
        | "notes"
        | "metadataFields"
      >
    >,
  ): void {
    const current = this.state.get().snapshotOptions;
    patchSignal(this.state, {
      snapshotOptions: {
        ...current,
        ...patch,
        runLabelEdited:
          patch.runLabel !== undefined ? true : current.runLabelEdited,
        tagsEdited: patch.tags !== undefined ? true : current.tagsEdited,
      },
    });
  }

  snapshotRequestOptions(): SnapshotRequestOptions {
    const options = this.state.get().snapshotOptions;
    return {
      commitMode:
        options.commitMode === "ask" ? options.commitDecision : options.commitMode,
      rememberCommitChoice:
        options.commitMode === "ask" && options.rememberCommitChoice,
      runLabel: normalizeOptionalText(options.runLabel),
      runLabelEdited: options.runLabelEdited,
      tags: parseTags(options.tags),
      notes: normalizeOptionalText(options.notes),
      extraFields: parseMetadataFields(options.metadataFields),
    };
  }

  setStatus(status: PanelStatus): void {
    patchSignal(this.state, { status });
  }

  /** Connect when signed out, sign out when signed in. Guarded by authBusy so a
   * double click does not start two flows (contract C-AUTH-04). */
  async toggleAuth(): Promise<void> {
    if (this.state.get().authBusy) {
      return;
    }
    patchSignal(this.state, { authBusy: true });
    try {
      if (this.state.get().readiness.canSnapshot) {
        await this.signOut();
      } else {
        const start = await this.api.startAuth();
        if (start.authUrl !== null) {
          openAuthWindow(start.authUrl);
        }
        await this.refreshAuth();
      }
    } catch (error) {
      patchSignal(this.state, { status: errorStatus(describeError(error)) });
    } finally {
      patchSignal(this.state, { authBusy: false });
    }
  }

  private async signOut(): Promise<void> {
    patchSignal(this.state, { status: info("Signing out...") });
    try {
      await this.api.signOut();
    } catch {
      patchSignal(this.state, {
        status: errorStatus("Unable to sign out of LabArchives."),
      });
      return;
    }
    await this.refreshAuth();
    patchSignal(this.state, { status: info("Signed out of LabArchives.") });
  }

  /** Refresh auth, keeping only the newest response when calls overlap. */
  async refreshAuth(): Promise<void> {
    const seq = ++this.authSeq;
    try {
      const auth = await this.api.authStatus();
      if (seq !== this.authSeq || this.disposed) {
        return;
      }
      this.schedulePendingAuthTimeout(auth);
      patchSignal(this.state, {
        auth,
        readiness: buildReadinessSection(auth),
        targetOptions: {
          ...this.state.get().targetOptions,
          availableNotebookNames: auth.storedNotebookNames,
        },
      });
    } catch (error) {
      if (seq !== this.authSeq) {
        return;
      }
      patchSignal(this.state, { status: errorStatus(describeError(error)) });
    }
  }

  async refreshActivity(): Promise<void> {
    try {
      const jobs = await this.api.listJobs(ACTIVITY_LIMIT);
      patchSignal(this.state, { activity: buildActivitySection(jobs) });
    } catch (error) {
      patchSignal(this.state, { status: errorStatus(describeError(error)) });
    }
  }

  async refreshPreview(body: unknown): Promise<void> {
    try {
      const preview = await this.api.previewSnapshot(body);
      patchSignal(this.state, {
        willBeSaved: buildWillBeSavedSection(preview),
      });
    } catch {
      if (this.state.get().busy) {
        return;
      }
      patchSignal(this.state, {
        status: warning(PREVIEW_REFRESH_FAILED_MESSAGE),
      });
    }
  }

  /** Submit one snapshot and follow it to a terminal state. Manual snapshots are
   * never throttled against each other (contract C-SNAP-01). */
  async snapshot(body: unknown): Promise<PanelStatus | null> {
    patchSignal(this.state, { busy: true, status: info(SAVING_MESSAGE) });
    try {
      const result = await this.api.submitSnapshot(body);
      if (result.status === "rejected") {
        const status = warning(result.message);
        patchSignal(this.state, { status });
        return status;
      }
      return await this.pollJob(result.coalescedInto ?? result.jobId);
    } catch (error) {
      const status = errorStatus(describeError(error));
      patchSignal(this.state, { status });
      if (status.message.startsWith("LabArchives session expired")) {
        await this.refreshAuth();
      }
      return status;
    } finally {
      patchSignal(this.state, { busy: false });
    }
  }

  private async pollJob(jobId: string): Promise<PanelStatus | null> {
    for (let attempt = 0; attempt < MAX_POLLS; attempt += 1) {
      if (this.disposed) {
        return null;
      }
      let jobs: SnapshotJobsResponse;
      try {
        jobs = await this.api.listJobs(ACTIVITY_LIMIT);
      } catch {
        const status = warning(STATUS_REFRESH_FAILED_MESSAGE);
        patchSignal(this.state, { status });
        return status;
      }
      patchSignal(this.state, { activity: buildActivitySection(jobs) });
      const record = jobs.jobs.find((job) => job.jobId === jobId);
      if (record !== undefined) {
        const status = statusForJobState(record.state, record.displayMessage);
        patchSignal(this.state, { status });
        if (record.errorCode === SESSION_EXPIRED_CODE) {
          await this.refreshAuth();
        }
        if (isTerminal(record.state)) {
          return status;
        }
      }
      await delay(this.pollIntervalMs);
    }
    return null;
  }

  private schedulePendingAuthTimeout(auth: AuthState): void {
    this.clearPendingAuthTimer();
    if (auth.status !== "pending") {
      return;
    }
    this.pendingAuthTimer = setTimeout(() => {
      void this.handlePendingAuthTimeout();
    }, this.authPendingTimeoutMs);
  }

  private clearPendingAuthTimer(): void {
    if (this.pendingAuthTimer === null) {
      return;
    }
    clearTimeout(this.pendingAuthTimer);
    this.pendingAuthTimer = null;
  }

  private async handlePendingAuthTimeout(): Promise<void> {
    if (this.disposed) {
      return;
    }
    await this.refreshAuth();
    if (this.state.get().readiness.canSnapshot) {
      return;
    }
    patchSignal(this.state, {
      status: warning(PENDING_AUTH_EXPIRED_MESSAGE),
    });
  }
}

function defaultSnapshotOptions(
  preferences: UserPreferences,
): SnapshotOptionsState {
  return {
    commitMode: preferences.defaultCommitMode,
    commitDecision:
      preferences.defaultCommitMode === "ask"
        ? "never"
        : preferences.defaultCommitMode,
    rememberCommitChoice: preferences.rememberCommitChoice,
    runLabel: preferences.defaultRunLabel ?? "",
    tags: preferences.defaultTags.join(", "),
    notes: "",
    metadataFields: "",
    runLabelEdited: false,
    tagsEdited: false,
  };
}

function normalizeOptionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function parseTags(value: string): string[] {
  const seen = new Set<string>();
  const tags: string[] = [];
  for (const raw of value.split(",")) {
    const tag = raw.trim();
    if (tag.length > 0 && !seen.has(tag)) {
      seen.add(tag);
      tags.push(tag);
    }
  }
  return tags;
}

function parseMetadataFields(value: string): Record<string, string> {
  const fields: Record<string, string> = {};
  for (const rawLine of value.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line.length === 0) {
      continue;
    }
    const separator = line.indexOf("=");
    if (separator <= 0) {
      continue;
    }
    const key = line.slice(0, separator).trim();
    const fieldValue = line.slice(separator + 1).trim();
    if (key.length > 0) {
      fields[key] = fieldValue;
    }
  }
  return fields;
}

function isTerminal(state: JobState): boolean {
  return state === "persisted" || state === "failed" || state === "abandoned";
}

function delay(ms: number): Promise<void> {
  return new Promise<void>((resolve) => {
    setTimeout(() => {
      resolve();
    }, ms);
  });
}

function openAuthWindow(url: string): void {
  try {
    window.open(url, "_blank", "noopener");
  } catch {
    // No window to open (non-browser host).
  }
}

function describeError(error: unknown): string {
  if (error instanceof ApiClientError) {
    return error.message;
  }
  return "The Save My Jupyter request failed.";
}
