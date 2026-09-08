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
    claims: [],
    activity_at: new Date().toISOString(),
    stale_eligible_at: "2099-01-01T00:00:00Z",
    messageability: { messageable: false },
    ...extra,
  }, () => {});
}

test("one status pill carries the quiet reason instead of a second badge", () => {
  const rendered = card({ mode: "parked", quiet_reason: "waiting on a blocking claim" });
  assert.deepEqual(
    byClass(rendered, "session-status-pill").map((node) => node.textContent),
    ["parked"],
  );
  const explain = byClass(rendered, "tooltip-info")[0];
  assert.equal(explain.tagName, "BUTTON");
  assert.equal(explain.getAttribute("aria-label"), "Why parked");
  assert.match(explain.getAttribute("data-tooltip"), /waiting on a blocking claim$/);
  // The explanation never joins the pill's own text, which is the state word
  // and nothing else — the pill is what a glance reads.
  assert.equal(byClass(rendered, "session-status-pill")[0].textContent, "parked");
});

test("a state with nothing to explain shows no affordance", () => {
  const rendered = card({});
  assert.deepEqual(
    byClass(rendered, "session-status-pill").map((node) => node.textContent),
    ["active"],
  );
  assert.equal(byClass(rendered, "tooltip-info").length, 0);
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
    ["session-harness h-other", "session-executor", "session-lane has-tooltip"],
  );
});

test("both header rows share one alignment and the lane keeps its whole name", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions.css",
    import.meta.url,
  ), "utf8");
  assert.match(
    css,
    /\.session-top,\s*\n\.universe-app-root \.session-state-line \{[^}]*align-items: center;/s,
  );
  assert.match(css, /\.session-state-line \{[^}]*min-height: 22px;/s);
  // The lane keeps the shared pill's non-shrinking box so a long lane name
  // moves to the next row of the wrapping identity line instead of squeezing.
  assert.match(
    css,
    /\.session-lane,[\s\S]*?\.session-model-tag \{[^}]*flex: 0 0 auto;/,
  );
  assert.doesNotMatch(css, /\.session-lane \{/);
});
