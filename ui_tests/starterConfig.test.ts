import assert from "node:assert/strict";
import test from "node:test";

import {
  EXISTING_CONFIG_HINT,
  REPO_CONFIG_FILENAME,
  STARTER_CONFIG_HINT,
  starterConfigButtonLabel,
  starterConfigCreateAvailable,
  starterConfigHint,
} from "../src/config/starterConfig";

void test("starter config create action is available only when config is missing", () => {
  assert.equal(starterConfigCreateAvailable(null), false);
  assert.equal(starterConfigCreateAvailable(false), true);
  assert.equal(starterConfigCreateAvailable(true), false);
});

void test("starter config labels describe checking and create states", () => {
  assert.equal(starterConfigButtonLabel(null), "Checking config");
  assert.equal(starterConfigButtonLabel(false), "Create starter config");
  assert.equal(starterConfigButtonLabel(true), "Create starter config");
});

void test("starter config hints describe missing and existing backend state", () => {
  assert.equal(REPO_CONFIG_FILENAME, ".save-my-jupyter.toml");
  assert.equal(starterConfigHint(false), STARTER_CONFIG_HINT);
  assert.equal(starterConfigHint(null), STARTER_CONFIG_HINT);
  assert.equal(starterConfigHint(true), EXISTING_CONFIG_HINT);
});
