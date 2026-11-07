import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { sessionCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";

function card(extra) {
  return sessionCard(new FakeDocument(), {
    session_id: "session-1",
    liveness: "active",
    executor: "codex",
    session_state: { status: "working", active_at: null, reason: "Waiting for the next turn.", presence: "present", activity: "working", intent: { state: "none" } },
    claims: [],
    activity_at: new Date().toISOString(),
    activity_quiet_at: "2099-01-01T00:00:00Z",
    messageability: { messageable: false },
    ...extra,
  }, () => {});
}

test("intent carries the recorded wait reason separately from activity", () => {
  const rendered = card({ session_state: { status: "waiting", active_at: null, reason: "Waiting for the next turn.", presence: "present", activity: "silent",
    intent: { state: "parked", reason: "waiting on a blocking claim" } } });
  assert.equal(byClass(rendered, "session-status-pill")[0].textContent, "Waiting");
  assert.match(byClass(rendered, "session-details")[0].getAttribute("data-tooltip"), /Intent: parked · waiting on a blocking claim/);
});

test("a state with nothing to explain shows no affordance", () => {
  const rendered = card({});
  assert.deepEqual(
    byClass(rendered, "session-status-pill").map((node) => node.textContent),
    ["Working"],
  );
  assert.equal(byClass(rendered, "session-details").length, 1);
});

test("the status pill leads the second header row, beside the model", () => {
  const rendered = card({ model: "gpt-5.6-sol" });
  const state = byClass(rendered, "session-state-line")[0];
  assert.ok(state, "the card renders a state row");
  assert.equal(state.children[0].classList.contains("session-status-pill"), true);
  assert.equal(state.children[1].classList.contains("session-model-line"), true);
  // The identity row keeps who is running and under whose name, and nothing
  // else: the pill used to sit in the middle of it.
  const top = byClass(rendered, "session-top")[0];
  assert.equal(byClass(top, "session-status-pill").length, 0);
  assert.deepEqual(
    top.children.map((node) => node.className),
    ["session-harness h-other", "session-executor row-link", "session-level has-tooltip", "tooltip-info has-tooltip session-details"],
  );
});

test("both header rows share one alignment and the level keeps its whole name", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions.css",
    import.meta.url,
  ), "utf8");
  assert.match(
    css,
    /\.session-top,\s*\n\.universe-app-root \.session-state-line \{[^}]*align-items: center;/s,
  );
  assert.match(css, /\.session-state-line \{[^}]*min-height: 22px;/s);
  // The level keeps the shared pill's non-shrinking box so a long level name
  // moves to the next row of the wrapping identity line instead of squeezing.
  assert.match(
    css,
    /\.session-level,[\s\S]*?\.session-model-tag \{[^}]*flex: 0 0 auto;/,
  );
  assert.doesNotMatch(css, /\.session-level \{/);
});
