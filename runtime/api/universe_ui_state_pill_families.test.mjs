// Which states are worth a colour, and which colour each one earns.
//
// A meaningful state absent from the family map falls through to grey, and
// grey reads as "nothing to see here" — so a session that parked itself, or
// a machine that went offline, disappeared into the same neutral as a state
// nobody needs to act on. These cases pin the semantics rather than the hex.

import assert from "node:assert/strict";
import test from "node:test";

import { pillFamilyForState } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_state_pills.js";

test("a declared park is its own family, not neutral and not an alert", () => {
  assert.equal(pillFamilyForState("parked"), "park");
  assert.notEqual(pillFamilyForState("parked"), pillFamilyForState("idle"));
  assert.notEqual(pillFamilyForState("parked"), pillFamilyForState("stale"));
});

test("states that need attention are amber, and failures stay red", () => {
  for (const state of ["waiting", "offline", "stale", "possibly stale"]) {
    assert.equal(pillFamilyForState(state), "warn", state);
  }
  for (const state of ["process-gone", "failed", "expired"]) {
    assert.equal(pillFamilyForState(state), "crit", state);
  }
});

test("healthy is green and genuinely neutral states stay grey", () => {
  assert.equal(pillFamilyForState("active"), "good");
  for (const state of ["ended", "idle", "unknown", "cancelled"]) {
    assert.equal(pillFamilyForState(state), "idle", state);
  }
});

test("every state a session card can show carries a deliberate family", () => {
  // The session vocabulary is small and fully enumerable, so none of it is
  // allowed to reach the map's unknown-value fallback by accident. "idle" is
  // retired as a primary-status pill — recency now lives on the timing line
  // as plain "active now" / "idle Xm" text, not a second pill — but the
  // family itself stays live for other muted states (ended, unknown, …) and
  // other pill families across the UI.
  const shown = [
    "active", "waiting", "parked", "probed", "stale",
    "possibly stale", "process-gone", "ended", "unknown",
  ];
  const families = new Map(shown.map((s) => [s, pillFamilyForState(s)]));
  assert.deepEqual([...families.entries()], [
    ["active", "good"],
    ["waiting", "warn"],
    ["parked", "park"],
    ["probed", "run"],
    ["stale", "warn"],
    ["possibly stale", "warn"],
    ["process-gone", "crit"],
    ["ended", "idle"],
    ["unknown", "idle"],
  ]);
});
