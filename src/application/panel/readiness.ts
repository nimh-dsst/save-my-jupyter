import type { AuthState } from "../../types";

export interface ReadinessSection {
  readonly canSnapshot: boolean;
  /** The auth-row description, one of the four phrasings in contract C-AUTH-03. */
  readonly authDescription: string;
  readonly authButtonLabel: string;
  /** Shown in Readiness when a snapshot is blocked (contract C-SNAP-02). */
  readonly blockedMessage: string | null;
}

const CONNECT_BLOCKED = "Connect LabArchives before creating a snapshot.";

export function buildReadinessSection(auth: AuthState): ReadinessSection {
  const authenticated = auth.status === "authenticated";
  return {
    canSnapshot: authenticated,
    authDescription: describeAuth(auth),
    authButtonLabel: authenticated ? "Sign out" : "Connect",
    blockedMessage: authenticated ? null : CONNECT_BLOCKED,
  };
}

function describeAuth(auth: AuthState): string {
  switch (auth.status) {
    case "authenticated":
      return `Authenticated as ${auth.userEmail ?? "unknown"}.`;
    case "pending":
      return "Authentication pending.";
    case "unauthenticated":
      return auth.storedUserEmail !== null
        ? `Not authenticated. Previously connected as ${auth.storedUserEmail}.`
        : "Not authenticated.";
  }
}
