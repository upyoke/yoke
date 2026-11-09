import assert from "node:assert/strict";
import test from "node:test";
import { sessionRosterFilters } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_roster_filters.js";
import { FakeDocument } from "./universe_ui_dom_test_support.mjs";
import { setStatuses, statusChecks } from "./universe_ui_sessions_view_test_support.mjs";

test("every chip combination filters the server status, including exited processes", () => {
  const filters = sessionRosterFilters(new FakeDocument(), () => {});
  const rows = ["working", "waiting", "ended"].map((status) => ({
    session_id: status, native_process_exited_at: "2026-11-06T12:00:00Z",
    session_state: {status, active_at: null, reason: "A plain sentence."},
  }));
  assert.deepEqual(statusChecks(filters.host).map((c) => c.getAttribute("aria-pressed") === "true"), [true, true, false]);
  assert.deepEqual(filters.apply(rows).map((r) => r.session_id), ["working", "waiting"]);
  for (let mask = 0; mask < 8; mask++) {
    const selected = rows.filter((_, i) => mask & (1 << i)).map((r) => r.session_id);
    setStatuses(filters.host, selected);
    assert.deepEqual(filters.apply(rows).map((r) => r.session_id), selected);
  }
});
