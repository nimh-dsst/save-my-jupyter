import assert from "node:assert/strict";
import test from "node:test";

import { requiresPanelSetup } from "../src/panelBehavior";

void test("requiresPanelSetup blocks unauthenticated states", () => {
  assert.equal(
    requiresPanelSetup({
      pendingRequestId: null,
      status: "unauthenticated",
      userEmail: null
    }),
    true
  );
  assert.equal(
    requiresPanelSetup({
      pendingRequestId: "pending-request",
      status: "pending",
      userEmail: null
    }),
    true
  );
});

void test("requiresPanelSetup allows authenticated state", () => {
  assert.equal(
    requiresPanelSetup({
      pendingRequestId: null,
      status: "authenticated",
      userEmail: "user@example.com"
    }),
    false
  );
});
