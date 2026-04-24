import assert from "node:assert/strict";
import test from "node:test";

import {
  AUTH_COMPLETION_CHANNEL_NAME,
  AUTH_COMPLETION_STORAGE_KEY,
  subscribeToAuthCompletionEvents,
  type AuthCompletionEvent
} from "../src/authEvents";

type MessageListener = (event: { data: unknown }) => void;
type StorageListener = (event: {
  key: string | null;
  newValue: string | null;
}) => void;

class FakeBroadcastChannel {
  static instances: FakeBroadcastChannel[] = [];

  private readonly listeners = new Set<MessageListener>();
  closed = false;

  constructor(readonly name: string) {
    FakeBroadcastChannel.instances.push(this);
  }

  addEventListener(type: string, listener: MessageListener): void {
    if (type === "message") {
      this.listeners.add(listener);
    }
  }

  removeEventListener(type: string, listener: MessageListener): void {
    if (type === "message") {
      this.listeners.delete(listener);
    }
  }

  postMessage(data: unknown): void {
    for (const candidate of FakeBroadcastChannel.instances) {
      if (candidate === this || candidate.name !== this.name) {
        continue;
      }

      for (const listener of candidate.listeners) {
        listener({ data });
      }
    }
  }

  close(): void {
    this.closed = true;
  }
}

class FakeWindow {
  private readonly storageListeners = new Set<StorageListener>();

  addEventListener(type: string, listener: StorageListener): void {
    if (type === "storage") {
      this.storageListeners.add(listener);
    }
  }

  removeEventListener(type: string, listener: StorageListener): void {
    if (type === "storage") {
      this.storageListeners.delete(listener);
    }
  }

  emitStorageEvent(event: {
    key: string | null;
    newValue: string | null;
  }): void {
    for (const listener of this.storageListeners) {
      listener(event);
    }
  }
}

void test("subscribeToAuthCompletionEvents receives broadcast messages", () => {
  const originalWindow = globalThis.window;
  const originalBroadcastChannel = globalThis.BroadcastChannel;
  const fakeWindow = new FakeWindow();
  const events: AuthCompletionEvent[] = [];
  FakeBroadcastChannel.instances = [];

  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: fakeWindow
  });
  Object.defineProperty(globalThis, "BroadcastChannel", {
    configurable: true,
    value: FakeBroadcastChannel
  });

  try {
    const subscription = subscribeToAuthCompletionEvents(event => {
      events.push(event);
    });
    const sender = new FakeBroadcastChannel(AUTH_COMPLETION_CHANNEL_NAME);

    sender.postMessage({
      message: null,
      requestId: "request-123",
      status: "authenticated"
    });

    assert.deepEqual(events, [
      {
        message: null,
        requestId: "request-123",
        status: "authenticated"
      }
    ]);

    subscription.dispose();

    sender.postMessage({
      message: "should be ignored",
      requestId: "request-123",
      status: "error"
    });

    assert.deepEqual(events, [
      {
        message: null,
        requestId: "request-123",
        status: "authenticated"
      }
    ]);
    assert.equal(FakeBroadcastChannel.instances[0]?.closed, true);
  } finally {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: originalWindow
    });
    Object.defineProperty(globalThis, "BroadcastChannel", {
      configurable: true,
      value: originalBroadcastChannel
    });
  }
});

void test("subscribeToAuthCompletionEvents falls back to storage events", () => {
  const originalWindow = globalThis.window;
  const originalBroadcastChannel = globalThis.BroadcastChannel;
  const fakeWindow = new FakeWindow();
  const events: AuthCompletionEvent[] = [];

  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: fakeWindow
  });
  Object.defineProperty(globalThis, "BroadcastChannel", {
    configurable: true,
    value: undefined
  });

  try {
    const subscription = subscribeToAuthCompletionEvents(event => {
      events.push(event);
    });

    fakeWindow.emitStorageEvent({
      key: AUTH_COMPLETION_STORAGE_KEY,
      newValue: JSON.stringify({
        message: "Authentication failed.",
        requestId: "request-456",
        status: "error",
        timestamp: Date.now()
      })
    });
    fakeWindow.emitStorageEvent({
      key: AUTH_COMPLETION_STORAGE_KEY,
      newValue: JSON.stringify({ invalid: true })
    });

    assert.deepEqual(events, [
      {
        message: "Authentication failed.",
        requestId: "request-456",
        status: "error"
      }
    ]);

    subscription.dispose();
  } finally {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: originalWindow
    });
    Object.defineProperty(globalThis, "BroadcastChannel", {
      configurable: true,
      value: originalBroadcastChannel
    });
  }
});
