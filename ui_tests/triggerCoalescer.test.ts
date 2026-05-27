import assert from "node:assert/strict";
import test from "node:test";

import { TriggerCoalescer } from "../src/notebook/triggerCoalescer";

void test("one run accumulates triggered cells and flushes them once", () => {
  const coalescer = new TriggerCoalescer<string>();
  coalescer.accumulate("nb", "cell-b");
  coalescer.accumulate("nb", "cell-a");
  coalescer.accumulate("nb", "cell-b"); // duplicate within the run

  assert.equal(coalescer.hasPending("nb"), true);
  assert.deepEqual(coalescer.flush("nb"), ["cell-a", "cell-b"]);
  // a second flush yields nothing -- the run resolved to one snapshot
  assert.deepEqual(coalescer.flush("nb"), []);
  assert.equal(coalescer.hasPending("nb"), false);
});

void test("notebooks accumulate independently", () => {
  const coalescer = new TriggerCoalescer<string>();
  coalescer.accumulate("nb-a", "cell-1");
  coalescer.accumulate("nb-b", "cell-2");

  assert.deepEqual(coalescer.flush("nb-a"), ["cell-1"]);
  assert.deepEqual(coalescer.flush("nb-b"), ["cell-2"]);
});

void test("flushing an idle notebook is empty", () => {
  assert.deepEqual(new TriggerCoalescer<string>().flush("nb"), []);
});
