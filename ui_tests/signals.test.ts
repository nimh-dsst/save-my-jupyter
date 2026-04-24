import assert from "node:assert/strict";
import test from "node:test";

import { createSignal, patchSignal } from "../src/signals";

void test("createSignal notifies subscribers when the value changes", () => {
  const signal = createSignal({
    count: 1
  });
  const snapshots: number[] = [];

  const unsubscribe = signal.subscribe(() => {
    snapshots.push(signal.get().count);
  });

  signal.set({
    count: 2
  });
  patchSignal(signal, {
    count: 3
  });
  unsubscribe();
  signal.set({
    count: 4
  });

  assert.deepEqual(snapshots, [2, 3]);
  assert.equal(signal.get().count, 4);
});
