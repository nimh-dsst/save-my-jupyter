import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

import { mergeTags, parseDirectives } from "../src/application/directives";

interface DirectiveCase {
  readonly name: string;
  readonly cells: string[];
  readonly runLabel: string | null;
  readonly tags: string[];
}

const fixtures = JSON.parse(
  readFileSync(join(process.cwd(), "fixtures", "directives.json"), "utf8"),
) as DirectiveCase[];

for (const fixture of fixtures) {
  void test(`shared directive fixture: ${fixture.name}`, () => {
    const result = parseDirectives(fixture.cells);
    assert.equal(result.runLabel, fixture.runLabel);
    assert.deepEqual([...result.tags], fixture.tags);
  });
}

void test("mergeTags unions, trims, and de-duplicates in first-seen order", () => {
  assert.deepEqual(mergeTags(["baseline", "gpu"], ["gpu", " final "], ["baseline"]), [
    "baseline",
    "gpu",
    "final",
  ]);
});

void test("mergeTags drops blank tags", () => {
  assert.deepEqual(mergeTags([" ", ""], ["kept"]), ["kept"]);
});
