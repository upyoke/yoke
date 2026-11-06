import assert from "node:assert/strict";
import test from "node:test";
import { sessionRosterFilters } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_roster_filters.js";
import { FakeDocument, allNodes } from "./universe_ui_dom_test_support.mjs";

test("the corrected legacy exit field excludes process-gone rows from Open", () => {
  const filters = sessionRosterFilters(new FakeDocument(), () => {});
  assert.deepEqual(filters.apply([
    { session_id: "present", liveness: "active" },
    { session_id: "gone", liveness: "active", native_process_exited_at: "2026-11-06T12:00:00Z" },
  ]).map((row) => row.session_id), ["present"]);
});

test("detailed groups partition the mixed roster without using posture or heartbeat", () => {
  const document = new FakeDocument();
  const filters = sessionRosterFilters(document, () => {});
  const stateControl = allNodes(filters.host).find((node) => node.tagName === "SELECT");
  const states = [
    ["present", "working", "none", "working"],
    ["present", "between_turns", "none", "between_turns"],
    ["present", "silent", "parked", "parked"],
    ["present", "between_turns", "awaiting", "parked"],
    ["present", "silent", "none", "silent"],
    ["gone", "silent", "none", "gone"],
    ["ended", "silent", "none", "ended"],
  ];
  const rows = states.map(([presence, activity, intent], index) => ({
    session_id: String(index), liveness: "active", turn_posture: "waiting",
    native_process_exited_at: "2026-11-06T12:00:00Z",
    session_state: { presence, activity, intent: { state: intent } },
  }));
  assert.equal(filters.apply(rows).length, 5);
  const selected = [];
  for (const group of ["working", "between_turns", "parked", "silent", "gone", "ended"]) {
    stateControl.value = group;
    const matching = filters.apply(rows);
    assert.deepEqual(matching.map((row) => row.session_id), states.flatMap(
      (state, index) => state[3] === group ? [String(index)] : [],
    ));
    selected.push(...matching);
  }
  assert.equal(new Set(selected).size, rows.length);
  assert.equal(selected.length, rows.length);
});
