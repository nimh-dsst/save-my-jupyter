import { URLExt } from "@jupyterlab/coreutils";
import { ServerConnection } from "@jupyterlab/services";

import {
  parseApiError,
  parseAuthState,
  parseSnapshotPreviewResponse,
  parseSnapshotSubmissionResult,
  type AuthState,
  type SnapshotPreviewResponse,
  type SnapshotSubmissionResult,
} from "./types";

const NAMESPACE = "save-my-jupyter";

/** Backend boundary: every response is parsed through a zod schema in types.ts,
 * so malformed payloads fail loudly rather than flowing into the UI. */
export class ApiClient {
  private readonly settings: ServerConnection.ISettings;

  constructor(settings?: ServerConnection.ISettings) {
    this.settings = settings ?? ServerConnection.makeSettings();
  }

  async submitSnapshot(body: unknown): Promise<SnapshotSubmissionResult> {
    return parseSnapshotSubmissionResult(
      await this.request("POST", ["snapshot"], body),
    );
  }

  async previewSnapshot(body: unknown): Promise<SnapshotPreviewResponse> {
    return parseSnapshotPreviewResponse(
      await this.request("POST", ["snapshot-preview"], body),
    );
  }

  async authStatus(): Promise<AuthState> {
    return parseAuthState(await this.request("GET", ["auth", "status"]));
  }

  async signOut(): Promise<void> {
    await this.request("POST", ["auth", "logout"]);
  }

  private async request(
    method: string,
    parts: readonly string[],
    body?: unknown,
  ): Promise<unknown> {
    const url = URLExt.join(this.settings.baseUrl, NAMESPACE, ...parts);
    const init: RequestInit = { method };
    if (body !== undefined) {
      init.body = JSON.stringify(body);
    }
    const response = await ServerConnection.makeRequest(url, init, this.settings);
    const payload: unknown = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new ApiClientError(parseErrorMessage(payload), response.status);
    }
    return payload;
  }
}

export class ApiClientError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
  }
}

function parseErrorMessage(payload: unknown): string {
  try {
    return parseApiError(payload).error.message;
  } catch {
    return "The Save My Jupyter request failed.";
  }
}
