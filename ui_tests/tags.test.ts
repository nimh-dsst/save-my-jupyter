import assert from "node:assert/strict";
import test from "node:test";

import { formatTagsInput, parseTagsInput } from "../src/tags";

void test("parseTagsInput splits comma-separated tags", () => {
  assert.deepEqual(parseTagsInput("baseline, experiment-1, final"), [
    "baseline",
    "experiment-1",
    "final",
  ]);
});

void test("parseTagsInput ignores empty entries while allowing trailing commas", () => {
  assert.deepEqual(parseTagsInput("baseline, "), ["baseline"]);
});

void test("formatTagsInput renders tags for the sidebar input", () => {
  assert.equal(
    formatTagsInput(["baseline", "experiment-1"]),
    "baseline, experiment-1",
  );
});
