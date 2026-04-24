import { z } from "zod";

export const AUTH_COMPLETION_CHANNEL_NAME = "save-my-jupyter-auth";
export const AUTH_COMPLETION_STORAGE_KEY = "save-my-jupyter.auth-event";

const authCompletionEventSchema = z.object({
  message: z.string().nullable().default(null),
  requestId: z.string(),
  status: z.enum(["authenticated", "error"])
});

export type AuthCompletionEvent = z.infer<typeof authCompletionEventSchema>;

export interface AuthCompletionSubscription {
  dispose(): void;
}

function emitIfValid(
  onEvent: (event: AuthCompletionEvent) => void,
  raw: unknown
): void {
  const parsed = authCompletionEventSchema.safeParse(raw);
  if (!parsed.success) {
    return;
  }
  onEvent(parsed.data);
}

export function subscribeToAuthCompletionEvents(
  onEvent: (event: AuthCompletionEvent) => void
): AuthCompletionSubscription {
  const cleanupCallbacks: (() => void)[] = [];

  if (typeof BroadcastChannel !== "undefined") {
    const channel = new BroadcastChannel(AUTH_COMPLETION_CHANNEL_NAME);
    const handleMessage = (event: MessageEvent<unknown>): void => {
      emitIfValid(onEvent, event.data);
    };
    channel.addEventListener("message", handleMessage);
    cleanupCallbacks.push(() => {
      channel.removeEventListener("message", handleMessage);
      channel.close();
    });
  }

  if (typeof window !== "undefined") {
    const handleStorage = (event: StorageEvent): void => {
      if (event.key !== AUTH_COMPLETION_STORAGE_KEY || event.newValue === null) {
        return;
      }

      try {
        emitIfValid(onEvent, JSON.parse(event.newValue) as unknown);
      } catch {
        return;
      }
    };

    window.addEventListener("storage", handleStorage);
    cleanupCallbacks.push(() => {
      window.removeEventListener("storage", handleStorage);
    });
  }

  return {
    dispose(): void {
      for (const cleanup of cleanupCallbacks) {
        cleanup();
      }
    }
  };
}
