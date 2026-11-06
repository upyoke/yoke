import assert from "node:assert/strict";
import test from "node:test";

import {
  killExplanation,
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

// The status pill's own (i) — not any explaining node on the card, since the
// lane chip and other facts explain themselves through the same primitive.
function statusExplanation(rendered) {
  const info = byClass(rendered, "tooltip-info")[0];
  return info ? info.getAttribute("data-tooltip") : null;
}

// A session past the staleness window with claims held, so every health state
// below differs only by the declaration or probe the row carries.
function quietHolder(extra) {
  return {
    session_id: "session-1",
    liveness: "active",
    executor: "codex",
    claims: ITEM_CLAIM,
    activity_at: "2026-08-22T11:00:00Z",
    activity_quiet_at: "2026-08-22T11:20:00Z",
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
    activity_quiet_at: new Date(Date.now() + 11.2 * 60000).toISOString(),
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

test("a kill reads as a cause of death on ended, never as its own liveness", () => {
  assert.equal(killExplanation({ liveness: "ended" }), "");
  // The pill stays one word whether or not a reason exists; the reason is
  // explanation, so it reaches the reader through the pill's (i) instead.
  assert.match(
    killExplanation({ ended_cause: "killed", termination_reason: "a long reason" }),
    /Reason: a long reason$/,
  );
  assert.ok(!killExplanation({ ended_cause: "killed" }).includes("Reason:"));

  const rendered = card({
    session_id: "killed-1",
    liveness: "ended",
    ended_cause: "killed",
    termination_reason: "operator stopped worker",
    terminated_at: "2026-08-22T12:05:00Z",
    executor: "codex",
    claims: [],
    activity_quiet_at: "2099-01-01T00:00:00Z",
    messageability: { messageable: false },
  });
  assert.equal(byClass(rendered, "session-health").length, 0);
  assert.equal(byClass(rendered, "session-kill-badge").length, 0);
  assert.match(
    statusExplanation(rendered),
    /^Terminated: .*Reason: operator stopped worker$/,
  );
  // The kill and its time ride the shared timing region every card carries.
  assert.match(byClass(rendered, "session-age")[0].textContent, /^killed /);
  assert.equal(
    byClass(rendered, "session-history-reason")[0].textContent,
    "Reason: operator stopped worker",
  );
  assert.equal(byClass(rendered, "session-status-pill")[0].textContent, "ended");
});


test("server facts stay independent of legacy liveness and posture", () => {
  for (const presence of ["present", "gone", "ended"]) {
    const rendered = card({
      ...quietHolder({}), liveness: "stale", turn_posture: "waiting",
      session_state: {
        presence, activity: "between_turns",
        intent: { state: "awaiting", reason: "CI is running" },
        next_actor: { actor: "ci_or_deploy", reason: "CI is running" },
      },
    });
    assert.equal(byClass(rendered, "session-status-pill")[0].textContent,
      presence === "present" ? "between turns" : presence);
    assert.equal(byClass(rendered, "session-intent")[0].textContent,
      "Intentawaiting · CI is running");
    assert.equal(byClass(rendered, "session-presence")[0].textContent,
      `Presence${presence}`);
    assert.doesNotMatch(byClass(rendered, "session-state-facts")[0].textContent, /stale|active/);
  }
});

test("an older serving response names missing state without guessing activity", () => {
  const rendered = card(quietHolder({}));
  assert.equal(byClass(rendered, "session-status-pill")[0].textContent, "unavailable");
  assert.match(statusExplanation(rendered), /refresh after the server upgrade/);
});
