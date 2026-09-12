// The one fixed order every machine card's quota rows are drawn in: the main
// weekly level first, the rest of the general pool next, then each
// model-specific pool kept together with its own windows adjacent. Ordering
// by measured headroom instead moved rows around as the readings moved and
// split a pool's two windows apart.

import assert from "node:assert/strict";
import test from "node:test";

import {
  sortPlanWindows,
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
    resets_at: new Date(Date.now() + 3 * 60 * 60 * 1000).toISOString(),
    ...facts,
  };
}

function textOf(host, className) {
  return byClass(host, className).map((node) => node.textContent);
}

function renderOneCard(relay) {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("div");
  renderMachinesPanel({ document: documentNode }, host, [relay], {});
  return host;
}

test("quota rows keep one pool-grouped order whatever order they arrive in", () => {
  // Shuffled on purpose, and with the two Spark windows deliberately split by
  // a general-pool row: the rendered order has to come from the structured
  // pool/window identity rather than from arrival.
  const shuffled = [
    windowReading({ window_kind: "rolling_5h", scope: "Spark" }),
    windowReading({ window_kind: "rolling_5h", scope: "all" }),
    windowReading({ window_kind: "rolling_7d", scope: "Spark" }),
    windowReading({ window_kind: "rolling_7d", scope: "all" }),
  ];
  const host = renderOneCard({
    machine_id: "machine-3",
    hostname: "laptop",
    state: "active",
    liveness: "connected",
    last_seen_at: new Date().toISOString(),
    surface_versions: { "claude-cli": "2.1.259" },
    surface_policies: [],
    plan_limits: {
      "claude-cli": {
        plan_tier: "max",
        observed_at: new Date().toISOString(),
        windows: shuffled,
      },
    },
  });

  // Main weekly first, the rest of the general pool next, then the
  // model-specific pool with its own two windows adjacent.
  assert.deepEqual(textOf(host, "machine-limit-name"), [
    "weekly · all",
    "rolling 5h · all",
    "weekly · Spark",
    "rolling 5h · Spark",
  ]);
  // Every row that arrived is still drawn: ordering never drops a reading.
  assert.equal(byClass(host, "machine-limit-row").length, shuffled.length);
});

test("an unknown pool or window keeps its group and sorts after known ones", () => {
  const ordered = sortPlanWindows([
    windowReading({ window_kind: "future_kind", scope: "Spark" }),
    windowReading({ window_kind: "rolling_5h", scope: "Zeta" }),
    windowReading({ window_kind: "monthly", scope: "" }),
    windowReading({ window_kind: "rolling_7d", scope: "Spark" }),
    windowReading({ window_kind: "rolling_7d", scope: "all" }),
  ]);

  // A scope-less window meters the general pool, so it groups there; an
  // unknown window kind sorts last inside its own pool instead of splitting
  // it, and pool names order stably.
  assert.deepEqual(ordered.map((window) => (
    `${window.window_kind}:${window.scope}`
  )), [
    "rolling_7d:all",
    "monthly:",
    "rolling_7d:Spark",
    "future_kind:Spark",
    "rolling_5h:Zeta",
  ]);
});

test("windows the sort cannot tell apart keep the order they arrived in", () => {
  const first = windowReading({ remaining_percent: 11 });
  const second = windowReading({ remaining_percent: 22 });

  assert.deepEqual(sortPlanWindows([first, second]), [first, second]);
  assert.deepEqual(sortPlanWindows([second, first]), [second, first]);
  assert.deepEqual(sortPlanWindows(undefined), []);
});
