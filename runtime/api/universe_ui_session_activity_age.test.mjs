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


function renderedActivityAge(documentNode, activityAt, extras = {}) {
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
      ...extras,
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

test("session status line leads with total age from offered_at", (t) => {
  const now = Date.parse("2026-08-27T12:00:00Z");
  const originalNow = Date.now;
  Date.now = () => now;
  t.after(() => { Date.now = originalNow; });

  const documentNode = new FakeDocument();
  const activityNow = new Date(now - 1_000).toISOString();
  assert.equal(
    renderedActivityAge(documentNode, activityNow, {
      offered_at: new Date(now - 3 * 60_000).toISOString(),
    }),
    "3m old · active now",
  );
  assert.equal(
    renderedActivityAge(documentNode, activityNow, {
      offered_at: new Date(now - 3 * 3_600_000).toISOString(),
      current_item: "YOK-1",
      claim_started_at: new Date(now - 60_000).toISOString(),
      holdings: { current: [{
        holding_kind: "work_claim", target_kind: "item", target: "YOK-1",
      }] },
    }),
    "3h old · claim held 1m · active now",
  );
  assert.equal(
    renderedActivityAge(documentNode, activityNow, { offered_at: "not-a-time" }),
    "active now",
  );
});
