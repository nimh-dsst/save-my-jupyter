import assert from "node:assert/strict";
import test from "node:test";

import type { Cell } from "@jupyterlab/cells";

import type { TriggerRun } from "../src/notebook/executionObserver";
import {
  firstNonBlankSourceLine,
  joinSource,
  notebookCellSources,
  triggerRunContentKey,
} from "../src/notebook/sourceText";

function fakeCell(
  source: unknown,
  options: {
    readonly id?: string;
    readonly outputs?: unknown;
    readonly metadata?: unknown;
    readonly executionCount?: number;
  } = {},
): Cell {
  return {
    model: {
      id: options.id ?? "cell-1",
      toJSON: () => ({
        execution_count: options.executionCount,
        id: options.id,
        metadata: options.metadata,
        outputs: options.outputs,
        source,
      }),
    },
  } as unknown as Cell;
}

function fakeRun(
  cell: Cell,
  options: {
    readonly cells?: readonly Cell[];
    readonly triggeredCellIds?: readonly string[];
  } = {},
): TriggerRun {
  return {
    lastCell: cell,
    notebook: { widgets: options.cells ?? [cell] },
    runOutcome: "success",
    triggeredCellIds: options.triggeredCellIds ?? [cell.model.id],
  } as unknown as TriggerRun;
}

void test("joinSource normalizes notebook source shapes", () => {
  assert.equal(joinSource("print('x')"), "print('x')");
  assert.equal(joinSource(["a", "b", 3, "c"]), "abc");
  assert.equal(joinSource(null), "");
});

void test("notebookCellSources reads string and list source cells", () => {
  assert.deepEqual(
    notebookCellSources({
      cells: [
        { source: "first" },
        { source: ["sec", "ond"] },
        { source: 12 },
        null,
      ],
    }),
    ["first", "second", "", ""],
  );
  assert.deepEqual(notebookCellSources({}), []);
});

void test("firstNonBlankSourceLine returns the trimmed first content line", () => {
  assert.equal(firstNonBlankSourceLine(fakeCell(["\n", "  alpha  \n"])), "alpha");
  assert.equal(firstNonBlankSourceLine(fakeCell("\n\n")), null);
});

void test("triggerRunContentKey includes notebook cell source, outputs, and tags", () => {
  const cell = fakeCell(["x = ", "1"], {
    id: "cell-1",
    outputs: [{ output_type: "stream", name: "stdout", text: "1\n" }],
  });
  const key = triggerRunContentKey(
    fakeRun(cell),
    { tags: [" review ", "baseline", "review"] },
  );

  assert.match(key, /"source":"x = 1"/);
  assert.match(key, /"text":"1\\n"/);
  assert.match(key, /"tags":\["baseline","review"\]/);
});

void test("triggerRunContentKey changes when any notebook cell output changes", () => {
  const triggerCell = fakeCell("x = 1", { id: "cell-1" });
  const first = fakeCell("x = 1", {
    id: "cell-2",
    outputs: [{ output_type: "stream", text: "1\n" }],
  });
  const second = fakeCell("x = 1", {
    id: "cell-2",
    outputs: [{ output_type: "stream", text: "2\n" }],
  });

  assert.notEqual(
    triggerRunContentKey(
      fakeRun(triggerCell, {
        cells: [triggerCell, first],
        triggeredCellIds: ["cell-1"],
      }),
    ),
    triggerRunContentKey(
      fakeRun(triggerCell, {
        cells: [triggerCell, second],
        triggeredCellIds: ["cell-1"],
      }),
    ),
  );
});

void test("triggerRunContentKey ignores execution count, ids, and metadata noise", () => {
  const triggerCell = fakeCell("x = 1", { id: "trigger-a" });
  const first = fakeCell("x = 1", {
    executionCount: 1,
    id: "cell-a",
    metadata: { collapsed: false },
    outputs: [{ execution_count: 1, output_type: "execute_result", data: { "text/plain": "1" } }],
  });
  const second = fakeCell("x = 1", {
    executionCount: 2,
    id: "cell-b",
    metadata: { collapsed: true },
    outputs: [{ execution_count: 2, output_type: "execute_result", data: { "text/plain": "1" } }],
  });

  assert.equal(
    triggerRunContentKey(
      fakeRun(triggerCell, {
        cells: [triggerCell, first],
        triggeredCellIds: ["trigger-a"],
      }),
    ),
    triggerRunContentKey(
      fakeRun(triggerCell, {
        cells: [triggerCell, second],
        triggeredCellIds: ["trigger-a"],
      }),
    ),
  );
});

void test("triggerRunContentKey changes when the normalized tag set changes", () => {
  const cell = fakeCell("x = 1");
  const run = fakeRun(cell);

  assert.notEqual(
    triggerRunContentKey(run, { tags: ["baseline"] }),
    triggerRunContentKey(run, { tags: ["baseline", "review"] }),
  );
});
