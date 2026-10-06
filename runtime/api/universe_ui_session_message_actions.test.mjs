import assert from "node:assert/strict";
import test from "node:test";

import {
  sessionMessageButton,
  sessionMessageDeliveryNote,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_roster_filters.js";
import { FakeDocument } from "./universe_ui_dom_test_support.mjs";

test("every session state offers its exact-session Message action", () => {
  for (const liveness of ["active", "stale", "ended"]) {
    for (const messageability of [
      {},
      { messageable: true, wake_available: true },
      { messageable: true, wake_available: false },
      { messageable: false, reason: "session_terminated" },
      { messageable: false, reason: "version_below_floor_or_unknown" },
      { messageable: false, reason: "unknown_surface" },
    ]) {
      const row = { session_id: `session-${liveness}`, liveness, messageability };
      const sent = [];
      const action = sessionMessageButton(new FakeDocument(), row,
        (sessionId) => sent.push(sessionId));
      assert.equal(action.textContent, "Message");
      action.dispatchEvent(new Event("click"));
      assert.deepEqual(sent, [row.session_id]);
    }
  }
});

test("delivery notes follow wake authority and preserve active hook delivery", () => {
  const desktop = { wake_authority: "operator", wake_available: false };
  const native = { wake_authority: "native", wake_available: true };
  assert.equal(sessionMessageDeliveryNote({
    liveness: "stale", messageability: desktop,
  }), "Queued — delivered when you wake this session.");
  assert.equal(sessionMessageDeliveryNote({
    liveness: "active", mode: "parked", messageability: desktop,
  }), "Queued — delivered when you wake this session.");
  assert.equal(sessionMessageDeliveryNote({
    liveness: "active", messageability: desktop,
  }), "");
  assert.equal(sessionMessageDeliveryNote({
    liveness: "stale", messageability: native,
  }), "");
  assert.equal(sessionMessageDeliveryNote({ liveness: "ended" }), "");
});
