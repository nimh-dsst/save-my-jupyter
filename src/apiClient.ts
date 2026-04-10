import { URLExt } from "@jupyterlab/coreutils";
import { ServerConnection } from "@jupyterlab/services";

import {
  type AuthStartResponse,
  type AuthState,
  type ConfigInitResponse,
  type EffectiveState,
  type NotebookContext,
  type SnapshotRequestPayload,
  type SnapshotSubmissionResult,
  type SnapshotUserMetadata,
  type WatchSyncResponse,
  parseApiError,
  parseAuthStartResponse,
  parseAuthState,
  parseConfigInitResponse,
  parseEffectiveState,
  parseSnapshotSubmissionResult,
  parseWatchSyncResponse
} from "./types";

export class ApiClient {
  constructor(
    private readonly settings: ServerConnection.ISettings = ServerConnection.makeSettings()
  ) {}

  async getState(notebookPath: string): Promise<EffectiveState> {
    const url = URLExt.join(this.settings.baseUrl, "save-my-jupyter", "state");
    const response = await ServerConnection.makeRequest(
      `${url}?notebook_path=${encodeURIComponent(notebookPath)}`,
      {},
      this.settings
    );
    return this.parseJsonResponse(response, parseEffectiveState);
  }

  async getAuthStatus(): Promise<AuthState> {
    const url = URLExt.join(
      this.settings.baseUrl,
      "save-my-jupyter",
      "auth",
      "status"
    );
    const response = await ServerConnection.makeRequest(url, {}, this.settings);
    return this.parseJsonResponse(response, parseAuthState);
  }

  async postSnapshot(
    payload: SnapshotRequestPayload
  ): Promise<SnapshotSubmissionResult> {
    const url = URLExt.join(
      this.settings.baseUrl,
      "save-my-jupyter",
      "snapshot"
    );
    const response = await ServerConnection.makeRequest(
      url,
      {
        body: JSON.stringify(payload),
        headers: { "Content-Type": "application/json" },
        method: "POST"
      },
      this.settings
    );
    return this.parseJsonResponse(response, parseSnapshotSubmissionResult);
  }

  async startAuth(): Promise<AuthStartResponse> {
    const url = URLExt.join(
      this.settings.baseUrl,
      "save-my-jupyter",
      "auth",
      "start"
    );
    const response = await ServerConnection.makeRequest(
      url,
      { method: "POST" },
      this.settings
    );
    return this.parseJsonResponse(response, parseAuthStartResponse);
  }

  async generateRepoConfig(notebookPath: string): Promise<ConfigInitResponse> {
    const url = URLExt.join(
      this.settings.baseUrl,
      "save-my-jupyter",
      "config",
      "init"
    );
    const response = await ServerConnection.makeRequest(
      url,
      {
        body: JSON.stringify({ notebook_path: notebookPath }),
        headers: { "Content-Type": "application/json" },
        method: "POST"
      },
      this.settings
    );
    return this.parseJsonResponse(response, parseConfigInitResponse);
  }

  async syncWatchRegistration(
    notebookContext: NotebookContext,
    watchPaths: string[],
    commitMode: SnapshotRequestPayload["commit_mode"],
    userMetadata: SnapshotUserMetadata
  ): Promise<WatchSyncResponse> {
    const url = URLExt.join(
      this.settings.baseUrl,
      "save-my-jupyter",
      "watch",
      "sync"
    );
    const response = await ServerConnection.makeRequest(
      url,
      {
        body: JSON.stringify({
          commit_mode: commitMode,
          notebook_context: notebookContext,
          user_metadata: userMetadata,
          watch_paths: watchPaths
        }),
        headers: { "Content-Type": "application/json" },
        method: "POST"
      },
      this.settings
    );
    return this.parseJsonResponse(response, parseWatchSyncResponse);
  }

  private async parseJsonResponse<T>(
    response: Response,
    parser: (raw: unknown) => T
  ): Promise<T> {
    const payload: unknown = await response.json();
    if (!response.ok) {
      const apiError = parseApiError(payload);
      throw new Error(apiError.error.message);
    }
    return parser(payload);
  }
}
