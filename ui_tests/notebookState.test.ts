import assert from "node:assert/strict";
import test from "node:test";

import type { Cell } from "@jupyterlab/cells";
import type { Notebook, NotebookPanel } from "@jupyterlab/notebook";

import {
  isFinalNotebookCell,
  readTargetOptions,
  updateTargetOptions,
} from "../src/notebook/notebookState";

void test("isFinalNotebookCell is true only for the notebook's last cell", () => {
  const first = fakeCell("first", "a = 1");
  const last = fakeCell("last", "b = 2");
  const notebook = { widgets: [first, last] } as unknown as Notebook;

  assert.equal(isFinalNotebookCell(notebook, first), false);
  assert.equal(isFinalNotebookCell(notebook, last), true);
  assert.equal(isFinalNotebookCell({ widgets: [] } as unknown as Notebook, last), false);
});

void test("isFinalNotebookCell ignores blank tail cells created by run-and-step", () => {
  const executed = fakeCell("executed", "result = 1");
  const blankTail = fakeCell("blank-tail", "");
  const notebook = { widgets: [executed, blankTail] } as unknown as Notebook;

  assert.equal(isFinalNotebookCell(notebook, executed), true);
});

void test("isFinalNotebookCell does not ignore later cells with source or output", () => {
  const executed = fakeCell("executed", "result = 1");
  const sourceTail = fakeCell("source-tail", "print(result)");
  const outputTail = fakeCell("output-tail", "", [{ output_type: "stream", text: "1\n" }]);

  assert.equal(
    isFinalNotebookCell({ widgets: [executed, sourceTail] } as unknown as Notebook, executed),
    false,
  );
  assert.equal(
    isFinalNotebookCell({ widgets: [executed, outputTail] } as unknown as Notebook, executed),
    false,
  );
});

void test("updateTargetOptions preserves spaces while editing target fields", () => {
  const panel = fakePanel();

  updateTargetOptions(panel, { notebookName: "Jupyter " });
  assert.equal(readTargetOptions(panel).notebookName, "Jupyter ");

  updateTargetOptions(panel, { notebookName: "Jupyter Snapshots" });
  assert.equal(readTargetOptions(panel).notebookName, "Jupyter Snapshots");
});

function fakeCell(id: string, source = "", outputs: unknown[] = []): Cell {
  return {
    model: {
      id,
      toJSON: () => ({ outputs, source }),
    },
  } as unknown as Cell;
}

function fakePanel(): NotebookPanel {
  let metadata: unknown;
  return {
    context: {
      model: {
        getMetadata: () => metadata,
        setMetadata: (_key: string, value: unknown) => {
          metadata = value;
        },
      },
    },
  } as unknown as NotebookPanel;
}
