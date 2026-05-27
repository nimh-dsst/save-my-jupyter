import assert from "node:assert/strict";
import test from "node:test";

import {
  readWatchedPaths,
  validateWatchedPathInput,
  withAddedWatchedPath,
  withoutWatchedPath,
  withWatchedPaths,
} from "../src/notebook/watchedPaths";

void test("watched path input normalizes separators and dot segments", () => {
  assert.deepEqual(
    validateWatchedPathInput(" outputs\\nested\\.\\result.csv "),
    {
      ok: true,
      path: "outputs/nested/result.csv",
    },
  );
});

void test("watched path input rejects unsafe values", () => {
  assert.deepEqual(validateWatchedPathInput(""), {
    ok: false,
    message: "Watched paths must not be empty.",
  });
  assert.deepEqual(validateWatchedPathInput("C:\\Users\\licc\\secret.txt"), {
    ok: false,
    message: "Watched paths must be relative.",
  });
  assert.deepEqual(validateWatchedPathInput("outputs/../secret.txt"), {
    ok: false,
    message: "Watched paths must stay within the notebook or repo root.",
  });
  assert.deepEqual(validateWatchedPathInput("./."), {
    ok: false,
    message: "Watched paths must include at least one path segment.",
  });
});

void test("watched path input rejects duplicates after normalization", () => {
  assert.deepEqual(validateWatchedPathInput("outputs\\result.csv", [
    "outputs/result.csv",
  ]), {
    ok: false,
    message: "That watched path is already listed.",
  });
});

void test("readWatchedPaths returns normalized safe unique metadata paths", () => {
  assert.deepEqual(
    readWatchedPaths({
      watched_paths: [
        "outputs\\result.csv",
        "../secret.txt",
        "outputs/result.csv",
        1,
        "figures",
      ],
    }),
    ["outputs/result.csv", "figures"],
  );
});

void test("withAddedWatchedPath appends and preserves notebook metadata", () => {
  const result = withAddedWatchedPath(
    {
      all_cells_trigger: true,
      watched_paths: ["outputs"],
    },
    "figures\\plot.png",
  );

  assert.deepEqual(result, {
    ok: true,
    path: "figures/plot.png",
    metadata: {
      all_cells_trigger: true,
      watched_paths: ["outputs", "figures/plot.png"],
    },
    watchedPaths: ["outputs", "figures/plot.png"],
  });
});

void test("withWatchedPaths and withoutWatchedPath replace only watched paths", () => {
  const metadata = withWatchedPaths({ trigger_cell_ids: ["cell-1"] }, [
    "outputs",
    "figures",
  ]);
  const removed = withoutWatchedPath(metadata, "outputs");

  assert.deepEqual(removed, {
    metadata: {
      trigger_cell_ids: ["cell-1"],
      watched_paths: ["figures"],
    },
    watchedPaths: ["figures"],
  });
});
