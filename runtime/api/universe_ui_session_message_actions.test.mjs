import assert from "node:assert/strict";
import test from "node:test";

import {
  sessionMessageButton,
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

test("Message tooltips never claim delivery is queued", () => {
  for (const messageability of [
    {wake_authority: "operator"}, {relay_connected: false}, {},
  ]) {
    const button = sessionMessageButton(new FakeDocument(),
      {session_id: "target", messageability}, () => {});
    assert.equal(button.getAttribute("data-tooltip"), "Message only session target");
  }
});
