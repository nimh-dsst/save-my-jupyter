import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_USER_PREFERENCES,
  UserPreferencesStore,
} from "../src/settings";

class FakeSettings {
  composite: Record<string, unknown> = {};
  readonly written: Record<string, unknown> = {};
  readonly changed = {
    connect: (listener: () => void): void => {
      this.listener = listener;
    },
  };
  private listener: (() => void) | null = null;

  set(key: string, value: unknown): Promise<void> {
    this.written[key] = value;
    this.composite[key] = value;
    this.listener?.();
    return Promise.resolve();
  }
}

class FakeRegistry {
  readonly settings = new FakeSettings();

  load(): Promise<FakeSettings> {
    return Promise.resolve(this.settings);
  }
}

void test("preferences store falls back when settings registry is unavailable", async () => {
  const store = new UserPreferencesStore(null);
  assert.deepEqual(await store.load(), DEFAULT_USER_PREFERENCES);
});

void test("preferences store remembers commit choice", async () => {
  const registry = new FakeRegistry();
  const store = new UserPreferencesStore(
    registry as unknown as ConstructorParameters<typeof UserPreferencesStore>[0],
  );
  await store.load();

  await store.rememberCommitChoice("always");

  assert.equal(registry.settings.written["defaultCommitMode"], "always");
  assert.equal(registry.settings.written["rememberCommitChoice"], true);
});
