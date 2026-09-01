import assert from "node:assert/strict";
import test from "node:test";

import {
  appendSessionAge,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_age.js";
import {
  FakeDocument,
  byClass,
} from "./universe_ui_dom_test_support.mjs";

function renderedActivityAge(documentNode, activityAt, extras = {}) {
  const body = documentNode.createElement("div");
  appendSessionAge(documentNode, body, {
    session_id: "session-1",
    liveness: "active",
    mode: "wait",
    executor: "codex",
    claims: [],
    coordination_leases: [],
    activity_at: activityAt,
    messageability: { messageable: false },
    ...extras,
  });
  return byClass(body, "session-age")[0].textContent;
}


// The server owns the executor-aware TTL. Activity age chooses active or idle
// copy only within a server-active session; it never recategorizes liveness.
test("session activity copy keeps server liveness authoritative", (t) => {
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
  // A long executor TTL can keep a quiet session alive without making its
  // activity recent.
  assert.equal(
    renderedActivityAge(documentNode, new Date(now - 1440 * 60_000).toISOString()),
    "idle 24h",
  );
  assert.equal(
    renderedActivityAge(
      documentNode, new Date(now - 1_000).toISOString(), { liveness: "stale" },
    ),
    "stale · activity just now",
  );
  assert.equal(
    renderedActivityAge(
      documentNode, new Date(now - 60_000).toISOString(), { liveness: "stale" },
    ),
    "stale 1m",
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
  for (const [elapsed, expected] of [
    [60_000, "1m old"],
    [4 * 3_600_000, "4h old"],
    [3 * 24 * 3_600_000, "3d old"],
  ]) {
    assert.equal(
      renderedActivityAge(documentNode, activityNow, {
        offered_at: new Date(now - elapsed).toISOString(),
      }),
      `${expected} · active now`,
    );
  }
  assert.equal(
    renderedActivityAge(documentNode, activityNow, {
      offered_at: new Date(now - 1_000).toISOString(),
    }),
    "created just now · active now",
  );
  assert.equal(
    renderedActivityAge(documentNode, activityNow, {
      offered_at: new Date(now + 60_000).toISOString(),
    }),
    "created just now · active now",
  );
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
    "worktree attached now · stale · activity just now",
  );
});

test("claim held duration follows the top rendered claim of any kind", (t) => {
  const now = Date.parse("2026-08-27T12:00:00Z");
  const originalNow = Date.now;
  Date.now = () => now;
  t.after(() => { Date.now = originalNow; });

  const documentNode = new FakeDocument();
  const activityNow = new Date(now - 1_000).toISOString();
  const ago = (ms) => new Date(now - ms).toISOString();
  const offered = { offered_at: ago(2 * 3_600_000) };

  assert.equal(
    renderedActivityAge(documentNode, activityNow, {
      ...offered,
      holdings: { current: [{
        holding_kind: "work_claim",
        target_kind: "steering",
        project_id: 1,
        strategy_docs: ["CURRENT-PLAN"],
        claimed_at: ago(12 * 60_000),
      }] },
    }),
    "2h old · claim held 12m · active now",
  );
  assert.equal(
    renderedActivityAge(documentNode, activityNow, {
      ...offered,
      holdings: { current: [{
        holding_kind: "work_claim",
        target_kind: "process",
        target: "process feed",
        claimed_at: ago(5 * 60_000),
      }] },
    }),
    "2h old · claim held 5m · active now",
  );
  assert.equal(
    renderedActivityAge(documentNode, activityNow, {
      ...offered,
      holdings: { current: [
        {
          holding_kind: "work_claim",
          target_kind: "steering",
          project_id: 1,
          strategy_docs: ["CURRENT-PLAN"],
          claimed_at: ago(12 * 60_000),
        },
        {
          holding_kind: "work_claim",
          target_kind: "item",
          target: "YOK-1",
          claimed_at: ago(2 * 3_600_000),
        },
      ] },
    }),
    "2h old · claim held 12m · active now",
  );
  assert.equal(
    renderedActivityAge(documentNode, activityNow, {
      ...offered,
      holdings: { current: [
        {
          holding_kind: "coordination",
          target_kind: "qa_admission",
          target: "QA_HOST:test-mac",
          claimed_at: ago(8 * 60_000),
        },
        {
          holding_kind: "work_claim",
          target_kind: "item",
          target: "YOK-1",
          claimed_at: ago(3_600_000),
        },
      ] },
    }),
    "2h old · claim held 8m · active now",
  );
});
