// Freshness display: a confirmed removal, a stale plan-limit reading, and a
// fresh reading whose window cannot compute headroom. Split from the base
// machine-card suite because these fixtures turn on real elapsed time
// (`observed_at` versus "now"), not the static facts the base suite covers.
import assert from "node:assert/strict";
import test from "node:test";

import {
  PLAN_LIMIT_FRESH_SECONDS,
  readingIsStale,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_machines_meters.js";
import {
  renderMachinesPanel,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_machines_panel.js";
import {
  FakeDocument,
  byClass,
} from "./universe_ui_dom_test_support.mjs";

function windowReading(facts = {}) {
  return {
    status: "ok",
    window_kind: "rolling_5h",
    scope: "all",
    meter: "primary",
    remaining_percent: 50,
    resets_at: "2026-09-04T14:30:00Z",
    ...facts,
  };
}

function textOf(host, className) {
  return byClass(host, className).map((node) => node.textContent);
}

function renderOneCard(relay) {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("div");
  renderMachinesPanel({ document: documentNode }, host, [relay]);
  return host;
}

test("ordinary refresh latency stays visible until the finite cutoff", () => {
  const observedAt = "2026-09-04T12:00:00Z";
  const cutoff = Date.parse(observedAt) + PLAN_LIMIT_FRESH_SECONDS * 1000;
  // The relay starts its normal refresh at four minutes. A UI load/redraw
  // after thirty seconds of provider and delivery latency is inside the reserve.
  const ordinaryDelivery = Date.parse(observedAt) + (4 * 60 + 30) * 1000;

  assert.equal(readingIsStale(observedAt, ordinaryDelivery), false);
  assert.equal(readingIsStale(observedAt, cutoff), false);
  assert.equal(readingIsStale(observedAt, cutoff + 1), true);
  assert.equal(readingIsStale("not-a-time", cutoff), true);
});

test("a confirmed removal reads absent and drops its stale version, never masked", () => {
  const host = renderOneCard({
    machine_id: "machine-4",
    hostname: "cleaned-up",
    state: "active",
    liveness: "connected",
    last_seen_at: new Date().toISOString(),
    // claude-cli still names a last-known version — the removal must
    // override that stale identity, not be hidden behind it.
    surface_versions: {
      "claude-cli": "2.1.259", "codex-cli": "1.0", "cursor-cli": "2026.09.02",
    },
    surface_confirmed_absent: ["claude-cli"],
    surface_policies: [],
    capacity: {},
  });

  assert.equal(byClass(host, "machine-surface-absent").length, 1);
  assert.deepEqual(
    textOf(host, "machine-surface-version"), ["1.0", "2026.09.02"],
  );
});

test("a stale plan-limit reading omits its tier, headroom, and quota alike", () => {
  const staleAt = new Date(Date.now() - 6 * 24 * 60 * 60 * 1000).toISOString();
  const host = renderOneCard({
    machine_id: "machine-5",
    hostname: "quiet-box",
    state: "idle",
    liveness: "silent",
    last_seen_at: staleAt,
    surface_versions: { "cursor-cli": "2026.09.02" },
    surface_policies: [],
    capacity: {},
    plan_limits: {
      "cursor-cli": {
        plan_tier: "Ultra",
        observed_at: staleAt,
        windows: [windowReading({
          remaining_percent: 23.652,
          resets_at: new Date(Date.now() - 60 * 1000).toISOString(),
        })],
      },
    },
  });

  assert.equal(byClass(host, "machine-plan-tier").length, 0);
  assert.deepEqual(textOf(host, "machine-limit-headroom").slice(1), ["—"]);
  assert.deepEqual(textOf(host, "machine-limit-quota").slice(1), ["—"]);
});

test("a fresh quota still shows when its window cannot compute headroom", () => {
  const host = renderOneCard({
    machine_id: "machine-6",
    hostname: "just-read",
    state: "active",
    liveness: "connected",
    last_seen_at: new Date().toISOString(),
    surface_versions: { "codex-cli": "1.0" },
    surface_policies: [],
    capacity: {},
    plan_limits: {
      "codex-cli": {
        plan_tier: "pro",
        observed_at: new Date().toISOString(),
        windows: [windowReading({ remaining_percent: 62, resets_at: null })],
      },
    },
  });

  assert.equal(byClass(host, "machine-plan-tier")[0].textContent, "pro");
  assert.deepEqual(textOf(host, "machine-limit-quota").slice(1), ["62%"]);
  assert.deepEqual(textOf(host, "machine-limit-headroom").slice(1), ["—"]);
});
