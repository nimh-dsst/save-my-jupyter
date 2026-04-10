import assert from "node:assert/strict";
import test from "node:test";

import { validateWatchedPath } from "../src/notebook/pathValidation";

void test("validateWatchedPath accepts and normalizes relative paths", () => {
  const result = validateWatchedPath("./outputs\\figures/result.png");

  assert.deepEqual(result, {
    ok: true,
    normalizedPath: "outputs/figures/result.png"
  });
});

void test("validateWatchedPath rejects absolute paths", () => {
  const result = validateWatchedPath("C:\\repo\\outputs\\result.csv");

  assert.equal(result.ok, false);
});

void test("validateWatchedPath rejects escaping parent traversals", () => {
  const result = validateWatchedPath("../secrets.txt");

  assert.deepEqual(result, {
    ok: false,
    message: "Watched paths must stay within the notebook or repo root."
  });
});
