import assert from "node:assert/strict";
import test from "node:test";

import {
  PARTIAL_MARK,
  UNREAD_DISPLAY,
  compactTokens,
  compactUsd,
  sessionCostDisplay,
  sessionTokensDisplay,
  summarizeSessionUsage,
  usageSummaryLabel,
  usageSummaryScope,
} from "../../packages/yoke-core/src/yoke_core/ui/static/session_usage_display.js";
import {
  appendSessionUsage,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_usage.js";
import {
  appendMachineUsage,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_machines_usage.js";
import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";

const MEASURED = {
  usage_tokens: 1_240_000,
  usage_status: "complete",
  usage_cost_usd: 12.5,
  usage_cost_status: "complete",
  usage_note: "1,240,000 tokens recorded",
};

test("compact figures stay readable at every scale", () => {
  assert.equal(compactTokens(999), "999");
  assert.equal(compactTokens(1_500), "1.5k");
  assert.equal(compactTokens(23_000), "23k");
  assert.equal(compactTokens(1_280_000), "1.3m");
  assert.equal(compactUsd(0.42), "$0.42");
  assert.equal(compactUsd(3.5), "$3.5");
  assert.equal(compactUsd(1234), "$1,234");
});

test("a session with no reading shows nothing rather than a zero", () => {
  assert.equal(sessionTokensDisplay({}), UNREAD_DISPLAY);
  assert.equal(sessionCostDisplay({}), UNREAD_DISPLAY);
  assert.equal(sessionTokensDisplay({ usage_tokens: 0 }), UNREAD_DISPLAY);
  assert.equal(sessionCostDisplay({ usage_cost_usd: null }), UNREAD_DISPLAY);
});

test("a figure from an incomplete reading is marked", () => {
  assert.equal(
    sessionTokensDisplay({ usage_tokens: 1_000, usage_status: "partial" }),
    `1k${PARTIAL_MARK}`,
  );
  assert.equal(
    sessionCostDisplay({ usage_cost_usd: 2, usage_cost_status: "partial" }),
    `$2${PARTIAL_MARK}`,
  );
});

test("a measured session shows its tokens beside its estimate", () => {
  assert.equal(sessionTokensDisplay(MEASURED), "1.2m");
  assert.equal(sessionCostDisplay(MEASURED), "$12.5");
});

test("the session card carries the explanation the figures dropped", () => {
  const documentNode = new FakeDocument();
  const body = documentNode.createElement("div");

  appendSessionUsage(documentNode, body, MEASURED);

  const line = byClass(body, "session-usage-line")[0];
  assert.ok(line, "the card renders a usage line");
  assert.equal(line.title, MEASURED.usage_note);
  const facts = byClass(body, "session-usage");
  assert.deepEqual(facts.map((node) => node.textContent), ["1.2m", "$12.5"]);
});

test("an unread session still renders, explaining why it is blank", () => {
  const documentNode = new FakeDocument();
  const body = documentNode.createElement("div");

  appendSessionUsage(documentNode, body, { session_id: "s" });

  const line = byClass(body, "session-usage-line")[0];
  assert.match(line.title, /no consumption recorded/);
  assert.deepEqual(
    byClass(body, "session-usage").map((node) => node.textContent),
    [UNREAD_DISPLAY, UNREAD_DISPLAY],
  );
});

test("a machine sums only the sessions that ran on it", () => {
  const summary = summarizeSessionUsage([
    { usage_tokens: 100, usage_status: "complete", usage_cost_usd: 1,
      usage_cost_status: "complete" },
    { usage_tokens: 400, usage_status: "complete", usage_cost_usd: 3,
      usage_cost_status: "complete" },
  ]);

  assert.equal(summary.tokens, 500);
  assert.equal(summary.cost, 4);
  assert.equal(summary.covered, 2);
  assert.equal(summary.total, 2);
  assert.equal(summary.partial, false);
});

test("a sum missing any member's reading is itself partial", () => {
  const summary = summarizeSessionUsage([
    { usage_tokens: 100, usage_status: "complete", usage_cost_usd: 1,
      usage_cost_status: "complete" },
    { session_id: "unread" },
  ]);

  assert.equal(summary.covered, 1);
  assert.equal(summary.total, 2);
  assert.equal(summary.partial, true);
  assert.equal(usageSummaryScope(summary), "1 of 2 sessions reported");
});

test("a sum of only unread sessions says so rather than reporting zero", () => {
  const summary = summarizeSessionUsage([{ session_id: "a" }, { session_id: "b" }]);

  assert.equal(summary.covered, 0);
  assert.equal(usageSummaryLabel(summary), "no consumption recorded for 2 sessions");
});

test("a partial member marks the total it contributed to", () => {
  const summary = summarizeSessionUsage([
    { usage_tokens: 100, usage_status: "partial", usage_cost_usd: 1,
      usage_cost_status: "complete" },
  ]);

  assert.equal(summary.partial, true);
  assert.equal(usageSummaryLabel(summary), `100${PARTIAL_MARK} · $1${PARTIAL_MARK}`);
});

test("the machine tile reports its scope beside its total", () => {
  const documentNode = new FakeDocument();
  const card = documentNode.createElement("div");
  const sessions = [
    { machine_id: "m1", usage_tokens: 1_000, usage_status: "complete",
      usage_cost_usd: 2, usage_cost_status: "complete" },
    { machine_id: "m1" },
    { machine_id: "m2", usage_tokens: 9_000, usage_status: "complete" },
  ];

  appendMachineUsage(documentNode, card, { machine_id: "m1" }, sessions);

  assert.equal(
    byClass(card, "machine-usage-scope")[0].textContent,
    "1 of 2 sessions reported",
  );
  assert.match(byClass(card, "machine-usage-total")[0].textContent, /^1k/);
});

test("a machine with no sessions on this page draws no usage line", () => {
  const documentNode = new FakeDocument();
  const card = documentNode.createElement("div");

  appendMachineUsage(documentNode, card, { machine_id: "m1" }, [
    { machine_id: "m2", usage_tokens: 10 },
  ]);

  assert.equal(byClass(card, "machine-usage").length, 0);
});

test("the machine scope says the estimate is not plan consumption", () => {
  const documentNode = new FakeDocument();
  const card = documentNode.createElement("div");

  appendMachineUsage(documentNode, card, { machine_id: "m1" }, [
    { machine_id: "m1", usage_tokens: 10, usage_status: "complete" },
  ]);

  assert.match(
    byClass(card, "machine-usage-scope")[0].title,
    /not consumption of any subscription plan/,
  );
});
