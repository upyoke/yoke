import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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
  fetchRecentUsageRows,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_machines_usage.js";
import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";

function fakeContext(rows) {
  const calls = [];
  return {
    calls,
    client: {
      call(request) {
        calls.push(request);
        return Promise.resolve({
          envelope: { success: true, result: { rows } },
        });
      },
    },
  };
}

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
  assert.equal(line.getAttribute("data-tooltip"), MEASURED.usage_note);
  const facts = byClass(body, "usage-stat-value");
  assert.deepEqual(facts.map((node) => node.textContent), ["1.2m", "$12.5"]);
  assert.deepEqual(
    byClass(body, "usage-stat-unit").map((node) => node.textContent),
    ["tokens", "API cost"],
  );
});

test("an unread session still renders, explaining why it is blank", () => {
  const documentNode = new FakeDocument();
  const body = documentNode.createElement("div");

  appendSessionUsage(documentNode, body, { session_id: "s" });

  const line = byClass(body, "session-usage-line")[0];
  assert.match(line.getAttribute("data-tooltip"), /no consumption recorded/);
  // The units stay on an unread session: naming what is missing is the point.
  assert.deepEqual(
    byClass(body, "usage-stat-value").map((node) => node.textContent),
    [UNREAD_DISPLAY, UNREAD_DISPLAY],
  );
  assert.deepEqual(
    byClass(body, "usage-stat-unit").map((node) => node.textContent),
    ["tokens", "API cost"],
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
  assert.equal(usageSummaryScope(summary), "");
});

test("cost coverage is stated separately when it trails token coverage", () => {
  const summary = summarizeSessionUsage([
    { usage_tokens: 100, usage_status: "complete", usage_cost_usd: 8.25,
      usage_cost_status: "complete" },
    { usage_tokens: 400, usage_status: "complete" },
  ]);

  assert.equal(summary.covered, 2);
  assert.equal(summary.costed, 1);
  assert.equal(usageSummaryScope(summary), "1 priced");
});

test("matching coverage says nothing extra", () => {
  const summary = summarizeSessionUsage([
    { usage_tokens: 100, usage_status: "complete", usage_cost_usd: 1,
      usage_cost_status: "complete" },
    { session_id: "unread" },
  ]);

  assert.equal(usageSummaryScope(summary), "");
});

test("nothing priced claims no cost coverage at all", () => {
  const summary = summarizeSessionUsage([
    { usage_tokens: 100, usage_status: "complete" },
  ]);

  assert.equal(summary.costed, 0);
  assert.equal(usageSummaryScope(summary), "");
});

test("a sum of only unread sessions says so rather than reporting zero", () => {
  const summary = summarizeSessionUsage([{ session_id: "a" }, { session_id: "b" }]);

  assert.equal(summary.covered, 0);
  assert.equal(usageSummaryLabel(summary), "no consumption recorded for 2 sessions");
  assert.equal(
    usageSummaryLabel(summarizeSessionUsage([{ session_id: "only" }])),
    "no consumption recorded for 1 session",
  );
});

test("a partial member marks the total it contributed to", () => {
  const summary = summarizeSessionUsage([
    { usage_tokens: 100, usage_status: "partial", usage_cost_usd: 1,
      usage_cost_status: "complete" },
  ]);

  assert.equal(summary.partial, true);
  assert.equal(usageSummaryLabel(summary), `100${PARTIAL_MARK} · $1${PARTIAL_MARK}`);
});

test("the machine tile carries the window in each label, with no separate heading", () => {
  const documentNode = new FakeDocument();
  const card = documentNode.createElement("div");
  const sessions = [
    { machine_id: "m1", usage_tokens: 1_000, usage_status: "complete",
      usage_cost_usd: 2, usage_cost_status: "complete" },
    { machine_id: "m1" },
    { machine_id: "m2", usage_tokens: 9_000, usage_status: "complete" },
  ];

  appendMachineUsage(documentNode, card, { machine_id: "m1" }, sessions);

  // The window rides each metric label, so the block holds the figures and
  // nothing above them to pair up by position.
  assert.equal(byClass(card, "machine-usage-block")[0].children.length, 1);
  assert.deepEqual(
    byClass(card, "usage-stat-value").map((node) => node.textContent),
    ["1k", "$2", "1"],
  );
  assert.deepEqual(
    byClass(card, "usage-stat-unit").map((node) => node.textContent),
    ["24h tokens", "24h API cost", "24h sessions"],
  );
  assert.equal(
    byClass(card, "machine-usage")[0].getAttribute("data-tooltip"),
    "estimated API-equivalent cost for this machine's sessions in the last "
    + "24 hours — those that ended in the window and those still running "
    + "that started in it — not consumption of any subscription plan; the "
    + "dollar total covers only the sessions that could be priced",
  );
});

test("the machine tile names its priced count when a session went unpriced", () => {
  const documentNode = new FakeDocument();
  const card = documentNode.createElement("div");

  appendMachineUsage(documentNode, card, { machine_id: "m1" }, [
    { machine_id: "m1", usage_tokens: 1_000, usage_status: "complete",
      usage_cost_usd: 8.25, usage_cost_status: "complete" },
    { machine_id: "m1", usage_tokens: 2_000, usage_status: "complete" },
  ]);

  assert.deepEqual(
    byClass(card, "usage-stat-value").map((node) => node.textContent),
    ["3k", "$8.25", "2"],
  );
  assert.match(
    byClass(card, "machine-usage")[0].getAttribute("data-tooltip"),
    /^1 priced\. estimated API-equivalent cost/,
  );
});

test("a zero-coverage window says so in place of the figures", () => {
  const documentNode = new FakeDocument();
  const card = documentNode.createElement("div");

  appendMachineUsage(documentNode, card, { machine_id: "m1" }, [
    { machine_id: "m1" },
    { machine_id: "m1" },
  ]);

  assert.equal(byClass(card, "machine-usage-block")[0].children.length, 1);
  assert.deepEqual(
    byClass(card, "usage-stat-unit").map((node) => node.textContent),
    ["no consumption recorded for 2 sessions"],
  );
});

test("a machine with no sessions in the window draws no usage line", () => {
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
    byClass(card, "machine-usage")[0].getAttribute("data-tooltip"),
    /not consumption of any subscription plan/,
  );
});

test("fetching 24h usage omits projects when the caller is unscoped", async () => {
  const context = fakeContext([{ machine_id: "m1", usage_tokens: 10 }]);

  const rows = await fetchRecentUsageRows(context);

  assert.deepEqual(context.calls, [
    { function: "sessions.list", payload: { usage_last_24h: true } },
  ]);
  assert.deepEqual(rows, [{ machine_id: "m1", usage_tokens: 10 }]);
});

test("fetching 24h usage scopes to the caller's selected projects", async () => {
  const context = fakeContext([]);

  await fetchRecentUsageRows(context, ["1", "2"]);

  assert.deepEqual(context.calls, [
    {
      function: "sessions.list",
      payload: { usage_last_24h: true, projects: ["1", "2"] },
    },
  ]);
});

test("usage stats wrap on the same narrow breakpoint as the rest of Sessions", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions_usage.css",
    import.meta.url,
  ), "utf8");
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*flex-wrap: wrap/);
});
