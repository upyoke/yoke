// A flow's destination is read from its typed target facts, never inferred
// from an absence. The defect this covers: a merge-only flow — no
// environment, no tier, no deploy stage — was labelled "Ephemeral", telling
// a reader it deployed per-run preview substrate it never touches.
import test from "node:test";
import assert from "node:assert/strict";

import { destinationLabel } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_delivery_flow_detail.js";

test("a registered environment is named by its own name", () => {
  assert.equal(
    destinationLabel({ target_environment: "prod", target_tier: "persistent" }),
    "prod",
  );
});

test("a declared ephemeral flow still reads as ephemeral", () => {
  assert.equal(
    destinationLabel({ target_environment: null, target_tier: "ephemeral" }),
    "Ephemeral",
  );
});

test("a merge-only flow says it deploys nowhere", () => {
  // Both typed facts absent and no deploy stage: this is the shape that was
  // being reported as a preview deployment.
  assert.equal(
    destinationLabel({ target_environment: null, target_tier: null }),
    "No deploy target",
  );
  assert.equal(destinationLabel({}), "No deploy target");
});

test("a persistent flow naming no environment is incomplete, not a preview", () => {
  assert.equal(
    destinationLabel({ target_environment: null, target_tier: "persistent" }),
    "Not set",
  );
});

test("blank strings are absence, not a destination", () => {
  assert.equal(
    destinationLabel({ target_environment: "   ", target_tier: "  " }),
    "No deploy target",
  );
});

test("a tier that arrives cased differently is still its own kind", () => {
  assert.equal(destinationLabel({ target_tier: "Ephemeral" }), "Ephemeral");
});

test("a missing row names no destination rather than throwing", () => {
  assert.equal(destinationLabel(undefined), "No deploy target");
  assert.equal(destinationLabel(null), "No deploy target");
});
