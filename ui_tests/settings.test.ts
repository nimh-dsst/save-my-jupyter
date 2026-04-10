import assert from "node:assert/strict";
import test from "node:test";

import { UserPreferencesStore } from "../src/settings";

class FakeStorage {
  private values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

void test("UserPreferencesStore falls back to defaults without storage", async () => {
  const originalWindow = globalThis.window;
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { localStorage: new FakeStorage() }
  });

  try {
    const store = new UserPreferencesStore("plugin-id", null);
    const preferences = await store.load();

    assert.equal(preferences.defaultCommitMode, "prompt");
    assert.equal(preferences.rememberCommitChoice, false);
    assert.deepEqual(preferences.defaultTags, []);
  } finally {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: originalWindow
    });
  }
});

void test("UserPreferencesStore saves and reloads local preferences", async () => {
  const originalWindow = globalThis.window;
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { localStorage: new FakeStorage() }
  });

  try {
    const store = new UserPreferencesStore("plugin-id", null);
    await store.save({
      defaultCommitMode: "always",
      defaultRunLabel: "baseline",
      defaultTags: ["tag-a", "tag-b"],
      rememberCommitChoice: true
    });

    const preferences = await store.load();

    assert.equal(preferences.defaultCommitMode, "always");
    assert.equal(preferences.defaultRunLabel, "baseline");
    assert.equal(preferences.rememberCommitChoice, true);
    assert.deepEqual(preferences.defaultTags, ["tag-a", "tag-b"]);
  } finally {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: originalWindow
    });
  }
});
