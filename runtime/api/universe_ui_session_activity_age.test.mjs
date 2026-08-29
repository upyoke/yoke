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


// The server owns the executor-aware TTL. A session it calls active stays
// active on the card however old its activity stamp is, and one it calls stale
// stays stale however fresh — the elapsed time beside the word never votes.
test("session liveness copy is the server's classification, not the elapsed time", (t) => {
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
    "active 1m",
  );
  // The live defect this replaces: 1440m of quiet under a 1440m TTL is still
  // active, and the card used to call it idle after 60 seconds.
  assert.equal(
    renderedActivityAge(documentNode, new Date(now - 1440 * 60_000).toISOString()),
    "active 24h",
  );
  assert.equal(
    renderedActivityAge(
      documentNode, new Date(now - 1_000).toISOString(), { liveness: "stale" },
    ),
    "stale now",
  );
  assert.equal(
    renderedActivityAge(
      documentNode, new Date(now - 1_000).toISOString(), { liveness: undefined },
    ),
    "unknown now",
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
  // Attribution names the relationship; the liveness word beside it is the
  // server's, so an attributed stale session never reads as active.
  assert.equal(
    renderedActivityAge(documentNode, activityNow, {
      liveness: "stale",
      current_item: "YOK-1",
      work_role: "worker",
    }),
    "worktree attached now · stale now",
  );
});
