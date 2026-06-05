import assert from "node:assert/strict";
import test from "node:test";

import {
  TriggerDebouncer,
  TRIGGER_SNAPSHOT_DEBOUNCE_MS,
} from "../src/notebook/triggerDebouncer";

interface Run {
  readonly notebook: string;
  readonly id: string;
  readonly source: string;
  readonly triggeredCellIds?: readonly string[];
}

void test("trigger debouncer waits for a quiet window before submitting", () => {
  const { debouncer, scheduler, submitted } = setupDebouncer();

  debouncer.schedule({ notebook: "nb-1", id: "run-1", source: "x = 1" });

  assert.deepEqual(ids(submitted), []);
  scheduler.advance(TRIGGER_SNAPSHOT_DEBOUNCE_MS - 1);
  assert.deepEqual(ids(submitted), []);
  scheduler.advance(1);
  assert.deepEqual(ids(submitted), ["run-1"]);
});

void test("trigger debouncer restarts the timer for adjacent trigger cells", () => {
  const { debouncer, scheduler, submitted } = setupDebouncer();
  debouncer.schedule({ notebook: "nb-1", id: "run-1", source: "x = 1" });

  debouncer.schedule({ notebook: "nb-1", id: "run-2", source: "x = 2" });
  scheduler.advance(TRIGGER_SNAPSHOT_DEBOUNCE_MS - 1_000);
  debouncer.schedule({ notebook: "nb-1", id: "run-3", source: "x = 3" });
  scheduler.advance(TRIGGER_SNAPSHOT_DEBOUNCE_MS - 1);

  assert.deepEqual(ids(submitted), []);
  scheduler.advance(1);
  assert.deepEqual(ids(submitted), ["run-3"]);
});

void test("trigger debouncer merges adjacent trigger runs before submitting", () => {
  const scheduler = new FakeScheduler();
  const submitted: Run[] = [];
  const debouncer = new TriggerDebouncer<string, Run>({
    debounceMs: 10_000,
    contentKey: (run) => run.source,
    merge: mergeRuns,
    onRun: (run) => {
      submitted.push(run);
    },
    setTimer: scheduler.setTimer,
    clearTimer: scheduler.clearTimer,
  });

  debouncer.schedule({
    notebook: "nb-1",
    id: "run-1",
    source: "x = 1",
    triggeredCellIds: ["cell-1"],
  });
  debouncer.schedule({
    notebook: "nb-1",
    id: "run-2",
    source: "x = 2",
    triggeredCellIds: ["cell-2"],
  });
  debouncer.schedule({
    notebook: "nb-1",
    id: "run-3",
    source: "x = 3",
    triggeredCellIds: ["cell-2", "cell-3"],
  });

  scheduler.advance(10_000);

  assert.deepEqual(ids(submitted), ["run-3"]);
  assert.deepEqual(submitted[0]?.triggeredCellIds, [
    "cell-1",
    "cell-2",
    "cell-3",
  ]);
});

void test("trigger debouncer computes content only for the settled merged run", () => {
  const scheduler = new FakeScheduler();
  const submitted: Run[] = [];
  const contentKeyCalls: string[] = [];
  const debouncer = new TriggerDebouncer<string, Run>({
    debounceMs: 10_000,
    contentKey: (run) => {
      contentKeyCalls.push(run.id);
      return run.source;
    },
    merge: mergeRuns,
    onRun: (run) => {
      submitted.push(run);
    },
    setTimer: scheduler.setTimer,
    clearTimer: scheduler.clearTimer,
  });

  debouncer.schedule({ notebook: "nb-1", id: "run-1", source: "x = 1" });
  debouncer.schedule({ notebook: "nb-1", id: "run-2", source: "x = 2" });

  assert.deepEqual(contentKeyCalls, []);
  debouncer.flush("nb-1");

  assert.deepEqual(contentKeyCalls, ["run-2"]);
  assert.deepEqual(ids(submitted), ["run-2"]);
});

void test("trigger debouncer waits for async content before submitting", async () => {
  let resolveContentKey!: (value: string) => void;
  const { debouncer, submitted } = setupDebouncer({
    contentKey: () =>
      new Promise<string>((resolve) => {
        resolveContentKey = resolve;
      }),
  });
  debouncer.schedule({ notebook: "nb-1", id: "run-1", source: "x = 1" });

  debouncer.flush("nb-1");
  assert.deepEqual(ids(submitted), []);

  resolveContentKey("x = 1");
  await Promise.resolve();

  assert.deepEqual(ids(submitted), ["run-1"]);
});

void test("trigger debouncer resolves async content in settled order", async () => {
  const contentRequests: {
    readonly id: string;
    readonly resolve: (value: string) => void;
  }[] = [];
  const { debouncer, submitted } = setupDebouncer({
    contentKey: (run) =>
      new Promise<string>((resolve) => {
        contentRequests.push({ id: run.id, resolve });
      }),
  });
  debouncer.schedule({ notebook: "nb-1", id: "run-0", source: "A" });
  debouncer.flush("nb-1");
  contentRequests[0]?.resolve("A");
  await settlePromises();

  debouncer.schedule({ notebook: "nb-1", id: "run-1", source: "B" });
  debouncer.flush("nb-1");
  debouncer.schedule({ notebook: "nb-1", id: "run-2", source: "A" });
  debouncer.flush("nb-1");

  assert.deepEqual(
    contentRequests.map((request) => request.id),
    ["run-0", "run-1"],
  );

  contentRequests[1]?.resolve("B");
  await settlePromises();
  assert.deepEqual(
    contentRequests.map((request) => request.id),
    ["run-0", "run-1", "run-2"],
  );

  contentRequests[2]?.resolve("A");
  await settlePromises();

  assert.deepEqual(ids(submitted), ["run-0", "run-1", "run-2"]);
});

void test("trigger debouncer can flush a settled burst before the quiet window", () => {
  const { debouncer, scheduler, submitted } = setupDebouncer();
  debouncer.schedule({ notebook: "nb-1", id: "run-1", source: "x = 1" });
  scheduler.advance(1_000);

  debouncer.flush("nb-1");
  scheduler.advance(10_000);

  assert.deepEqual(ids(submitted), ["run-1"]);
});

void test("trigger debouncer starts a new burst after the quiet window", () => {
  const { debouncer, scheduler, submitted } = setupDebouncer();
  debouncer.schedule({ notebook: "nb-1", id: "run-1", source: "x = 1" });
  scheduler.advance(10_000);

  debouncer.schedule({ notebook: "nb-1", id: "run-2", source: "x = 2" });

  assert.deepEqual(ids(submitted), ["run-1"]);
  scheduler.advance(TRIGGER_SNAPSHOT_DEBOUNCE_MS - 1);
  assert.deepEqual(ids(submitted), ["run-1"]);
  scheduler.advance(1);
  assert.deepEqual(ids(submitted), ["run-1", "run-2"]);
});

void test("trigger debouncer skips unchanged content after a submitted burst", () => {
  const { debouncer, scheduler, submitted } = setupDebouncer();
  debouncer.schedule({ notebook: "nb-1", id: "run-1", source: "x = 1" });
  scheduler.advance(10_000);

  debouncer.schedule({ notebook: "nb-1", id: "run-2", source: "x = 1" });
  scheduler.advance(10_000);

  assert.deepEqual(ids(submitted), ["run-1"]);
});

void test("trigger debouncer submits again when the content key changes", () => {
  const { debouncer, scheduler, submitted } = setupDebouncer();
  debouncer.schedule({ notebook: "nb-1", id: "run-1", source: "x = 1" });
  scheduler.advance(10_000);

  debouncer.schedule({ notebook: "nb-1", id: "run-2", source: "x = 1|tag=review" });
  scheduler.advance(10_000);

  assert.deepEqual(ids(submitted), ["run-1", "run-2"]);
});

void test("trigger debouncer tracks notebooks independently", () => {
  const { debouncer, scheduler, submitted } = setupDebouncer();
  debouncer.schedule({ notebook: "nb-1", id: "a-1", source: "x = 1" });
  debouncer.schedule({ notebook: "nb-2", id: "b-1", source: "x = 1" });

  debouncer.schedule({ notebook: "nb-1", id: "a-2", source: "x = 2" });
  scheduler.advance(TRIGGER_SNAPSHOT_DEBOUNCE_MS / 2);
  debouncer.schedule({ notebook: "nb-2", id: "b-2", source: "x = 2" });
  scheduler.advance(TRIGGER_SNAPSHOT_DEBOUNCE_MS / 2);

  assert.deepEqual(ids(submitted), ["a-2"]);
  scheduler.advance(TRIGGER_SNAPSHOT_DEBOUNCE_MS / 2);
  assert.deepEqual(ids(submitted), ["a-2", "b-2"]);
});

void test("trigger debouncer clears pending snapshots on dispose", () => {
  const { debouncer, scheduler, submitted } = setupDebouncer();
  debouncer.schedule({ notebook: "nb-1", id: "run-1", source: "x = 1" });

  debouncer.dispose();
  scheduler.advance(10_000);

  assert.deepEqual(ids(submitted), []);
});

void test("trigger debouncer skips async submissions after dispose", async () => {
  let resolveContentKey!: (value: string) => void;
  const { debouncer, submitted } = setupDebouncer({
    contentKey: () =>
      new Promise<string>((resolve) => {
        resolveContentKey = resolve;
      }),
  });
  debouncer.schedule({ notebook: "nb-1", id: "run-1", source: "x = 1" });
  debouncer.flush("nb-1");

  debouncer.dispose();
  resolveContentKey("x = 1");
  await settlePromises();

  assert.deepEqual(ids(submitted), []);
});

function setupDebouncer(
  options: {
    readonly contentKey?: (run: Run) => string | Promise<string>;
  } = {},
): {
  readonly debouncer: TriggerDebouncer<string, Run>;
  readonly scheduler: FakeScheduler;
  readonly submitted: Run[];
} {
  const scheduler = new FakeScheduler();
  const submitted: Run[] = [];
  return {
    debouncer: new TriggerDebouncer<string, Run>({
      debounceMs: TRIGGER_SNAPSHOT_DEBOUNCE_MS,
      contentKey: options.contentKey ?? ((run) => run.source),
      onRun: (run) => {
        submitted.push(run);
      },
      setTimer: scheduler.setTimer,
      clearTimer: scheduler.clearTimer,
    }),
    scheduler,
    submitted,
  };
}

function mergeRuns(previous: Run, next: Run): Run {
  return {
    ...next,
    triggeredCellIds: [
      ...new Set([
        ...(previous.triggeredCellIds ?? []),
        ...(next.triggeredCellIds ?? []),
      ]),
    ],
  };
}

function ids(runs: readonly Run[]): string[] {
  return runs.map((run) => run.id);
}

async function settlePromises(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

class FakeScheduler {
  private now = 0;
  private nextId = 1;
  private readonly timers = new Map<number, { due: number; callback: () => void }>();

  readonly setTimer = (callback: () => void, ms: number): number => {
    const id = this.nextId;
    this.nextId += 1;
    this.timers.set(id, { due: this.now + ms, callback });
    return id;
  };

  readonly clearTimer = (timer: unknown): void => {
    if (typeof timer === "number") {
      this.timers.delete(timer);
    }
  };

  advance(ms: number): void {
    this.now += ms;
    while (this.runNextDueTimer()) {
      // Keep draining timers that became due during callbacks.
    }
  }

  private runNextDueTimer(): boolean {
    const dueTimers = [...this.timers.entries()]
      .filter(([, timer]) => timer.due <= this.now)
      .sort((left, right) => left[1].due - right[1].due);
    const next = dueTimers[0];
    if (next === undefined) {
      return false;
    }
    const [id, timer] = next;
    this.timers.delete(id);
    timer.callback();
    return true;
  }
}
