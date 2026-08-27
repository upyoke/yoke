import assert from "node:assert/strict";
import test from "node:test";

import {
  sessionCard,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import {
  FakeDocument,
  byClass,
} from "./universe_ui_dom_test_support.mjs";


const WHO = { label: "member", value: () => "Ben" };


function renderedActivityAge(documentNode, activityAt) {
  const card = sessionCard(
    documentNode,
    {
      session_id: "session-1",
      liveness: "active",
      mode: "wait",
      executor: "codex",
      claims: [],
      coordination_leases: [],
      activity_at: activityAt,
      messageability: { messageable: false },
    },
    WHO,
    "hosted",
    () => {},
  );
  return byClass(card, "session-age")[0].textContent;
}


test("session activity copy changes at the relative-time minute floor", (t) => {
  const now = Date.parse("2026-08-27T12:00:00Z");
  const originalNow = Date.now;
  Date.now = () => now;
  t.after(() => { Date.now = originalNow; });

  const documentNode = new FakeDocument();
  assert.equal(
    renderedActivityAge(documentNode, new Date(now - 59_999).toISOString()),
    "active now",
  );
  assert.equal(
    renderedActivityAge(documentNode, new Date(now - 60_000).toISOString()),
    "idle 1m",
  );
});
