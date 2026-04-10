import type { AuthState } from "./types";

export function requiresPanelSetup(auth: AuthState): boolean {
  return auth.status !== "authenticated";
}
