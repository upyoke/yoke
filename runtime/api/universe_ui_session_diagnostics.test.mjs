import assert from "node:assert/strict";
import test from "node:test";

import {
  killBadgeLabel,
  killBadgeTitle,
  sessionHealthState,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_diagnostics.js";
import {
  sessionCard,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import {
  FakeDocument,
  byClass,
} from "./universe_ui_dom_test_support.mjs";

const ITEM_CLAIM = [{ target_kind: "item", target: "YOK-1" }];

function card(row) {
  return sessionCard(new FakeDocument(), row, () => {});
}

// A session past the staleness window with claims held, so every health state
// below differs only by the declaration or probe the row carries.
function quietHolder(extra) {
  return {
    session_id: "session-1",
    liveness: "stale",
    executor: "codex",
    claims: ITEM_CLAIM,
    activity_at: "2026-08-22T11:00:00Z",
    stale_eligible_at: "2026-08-22T11:20:00Z",
    messageability: { messageable: false },
    ...extra,
  };
}

test("session card keeps the latest message badge and drops the removed facts", () => {
  const createdAt = new Date(Date.now() - 4.2 * 60000).toISOString();
  const rendered = card({
    session_id: "session-1",
    liveness: "active",
    executor: "codex", model: "gpt-5.6-sol",
    reasoning_effort: "max", context_window_tokens: 258_400,
    claims: [],
    activity_at: createdAt,
    latest_message: {
      message_id: "message-1",
      state: "pending",
      created_at: createdAt,
    },
    end_blocker: { status: "has_claims", active_claim_count: 1 },
    effective_stale_ttl_minutes: 60,
    stale_eligible_at: new Date(Date.now() + 11.2 * 60000).toISOString(),
    machine_name: "test-mac",
    relay: "connected",
    messageability: {
      messageable: true, wake_available: true, relay_connected: true,
    },
  });

  const body = byClass(rendered, "session-card-body")[0];
  const rows = body.children.map((child) => child.className);
  assert.equal(
    rows.indexOf("session-latest-message"),
    rows.indexOf("session-relay") + 1,
  );
  assert.equal(byClass(rendered, "session-message-button")[0].textContent, "Message");
  assert.equal(byClass(rendered, "session-latest-label")[0].textContent, "Latest:");
  assert.deepEqual(
    byClass(rendered, "session-model-tag").map(
      (tag) => [tag.textContent, tag.getAttribute("data-model-fact")],
    ),
    [["MAX", "reasoning-effort"], ["258k", "context-window"]],
  );
  assert.equal(
    byClass(rendered, "session-message-badge")[0].textContent,
    "pending · 4m",
  );
  assert.equal(byClass(rendered, "session-end-blocker").length, 0);
  assert.equal(byClass(rendered, "session-stale-context").length, 0);
  assert.equal(byClass(rendered, "session-health").length, 0);
});

test("a declared wait reads as waiting, not as a session suspected of being gone", () => {
  const dependency = sessionHealthState(
    quietHolder({
      declared_wait: {
        kind: "dependency",
        item: "YOK-1",
        blocking_item: "YOK-2",
        gate_point: "activation",
        blocking_status: "implementing",
      },
    }),
    Date.parse("2026-08-22T12:00:00Z"),
  );
  assert.equal(dependency.state, "waiting");
  assert.equal(dependency.label, "waiting");
  assert.equal(dependency.detail, "gated on YOK-2 (implementing)");

  const posture = sessionHealthState(
    quietHolder({ declared_wait: { kind: "turn_posture" } }),
    Date.parse("2026-08-22T12:00:00Z"),
  );
  assert.equal(posture.state, "waiting");
  assert.equal(posture.detail, "turn parked for an answer");
});

test("an open probe replaces possibly-stale, which needs no declaration at all", () => {
  const probed = sessionHealthState(
    quietHolder({
      stale_alive_probe: {
        state: "injected",
        created_at: "2026-08-22T11:50:00Z",
      },
    }),
    Date.parse("2026-08-22T12:00:00Z"),
  );
  assert.equal(probed.state, "probed");
  assert.equal(probed.label, "probed");
  assert.match(probed.detail, /^awaiting response · asked /);

  const unaccounted = sessionHealthState(
    quietHolder({}),
    Date.parse("2026-08-22T12:00:00Z"),
  );
  assert.equal(unaccounted.state, "stale");
  assert.equal(unaccounted.label, "possibly stale");

  // A declared wait outranks a probe: the session already said why it is quiet.
  const both = sessionHealthState(
    quietHolder({
      declared_wait: { kind: "turn_posture" },
      stale_alive_probe: { state: "pending", created_at: "2026-08-22T11:50:00Z" },
    }),
    Date.parse("2026-08-22T12:00:00Z"),
  );
  assert.equal(both.state, "waiting");
});

test("process-gone evidence outranks age and tells the operator how to act", () => {
  const row = quietHolder({
    liveness: "active",
    claims: [],
    holdings: { current: [{ holding_kind: "strategy_document" }] },
    native_process: {
      state: "gone",
      observed_at: "2026-08-22T11:59:00Z",
    },
    stale_eligible_at: "2026-08-22T12:30:00Z",
  });
  const health = sessionHealthState(row, Date.parse("2026-08-22T12:00:00Z"));
  assert.deepEqual(health, {
    state: "process-gone",
    label: "process gone",
    detail: "claims held — terminate deliberately if dead",
  });
  const rendered = card(row);
  assert.equal(byClass(rendered, "session-health-pill")[0].textContent, "process gone");
  assert.equal(
    byClass(rendered, "session-health-detail")[0].textContent,
    "claims held — terminate deliberately if dead",
  );
});

test("health stays silent for active, claim-free, and ended sessions", () => {
  const now = Date.parse("2026-08-22T12:00:00Z");
  assert.equal(
    sessionHealthState(
      quietHolder({ liveness: "active", stale_eligible_at: "2026-08-22T12:30:00Z" }),
      now,
    ),
    null,
  );
  assert.equal(sessionHealthState(quietHolder({ claims: [] }), now), null);
  assert.equal(sessionHealthState(quietHolder({ liveness: "ended" }), now), null);
});

test("the health pill renders its state and detail on the card", () => {
  const rendered = card(quietHolder({
    stale_eligible_at: "2020-01-01T00:00:00Z",
    declared_wait: {
      kind: "dependency",
      item: "YOK-1",
      blocking_item: "YOK-2",
      blocking_status: "implementing",
    },
  }));
  const pill = byClass(rendered, "session-health-pill")[0];
  assert.equal(pill.textContent, "waiting");
  assert.equal(pill.getAttribute("data-state"), "waiting");
  assert.equal(
    byClass(rendered, "session-health-detail")[0].textContent,
    "gated on YOK-2 (implementing)",
  );
});

test("a kill reads as a cause of death on ended, never as its own liveness", () => {
  assert.equal(killBadgeLabel({ liveness: "ended" }), "");
  assert.equal(killBadgeLabel({ ended_cause: "killed" }), "killed");
  // The label stays one word whether or not a reason exists; the reason is
  // hover detail, so it reaches the reader through the title instead.
  assert.equal(
    killBadgeLabel({ ended_cause: "killed", termination_reason: "a long reason" }),
    "killed",
  );
  assert.match(
    killBadgeTitle({ ended_cause: "killed", termination_reason: "a long reason" }),
    /Reason: a long reason$/,
  );
  assert.ok(!killBadgeTitle({ ended_cause: "killed" }).includes("Reason:"));

  const rendered = card({
    session_id: "killed-1",
    liveness: "ended",
    ended_cause: "killed",
    termination_reason: "operator stopped worker",
    terminated_at: "2026-08-22T12:05:00Z",
    executor: "codex",
    claims: [],
    stale_eligible_at: "2099-01-01T00:00:00Z",
    messageability: { messageable: false },
  });
  assert.equal(byClass(rendered, "session-health").length, 0);
  const badge = byClass(rendered, "session-kill-badge")[0];
  assert.equal(badge.textContent, "killed");
  assert.match(badge.title, /Reason: operator stopped worker$/);
});
