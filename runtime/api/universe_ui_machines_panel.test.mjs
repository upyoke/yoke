import assert from "node:assert/strict";
import test from "node:test";

import {
  headroomMeterPosition,
  planWindowHeadroom,
  renderMachinesPanel,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_machines_panel.js";
import {
  FakeDocument,
  byClass,
} from "./universe_ui_dom_test_support.mjs";

const NOW = Date.parse("2026-09-04T12:00:00Z");

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

test("headroom uses a 100 percent pivot with a bounded logarithmic tail", () => {
  assert.equal(planWindowHeadroom(windowReading(), NOW), 100);
  assert.equal(planWindowHeadroom(windowReading({
    resets_at: "2026-09-04T13:15:00Z",
  }), NOW), 200);
  assert.equal(planWindowHeadroom({ status: "unknown" }, NOW), null);
  assert.equal(headroomMeterPosition(0), 0);
  assert.equal(headroomMeterPosition(100), 68);
  assert.equal(headroomMeterPosition(1000), 100);
  assert.equal(headroomMeterPosition(5000), 100);
  assert.ok(headroomMeterPosition(200) > 68);
  assert.ok(headroomMeterPosition(200) < 100);
});

test("a machine card draws capacity and every launchable surface pool", () => {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("div");
  const context = { document: documentNode };
  renderMachinesPanel(context, host, [{
    machine_id: "machine-1",
    hostname: "studio",
    state: "active",
    liveness: "connected",
    surface_versions: {
      "claude-cli": "2.0",
      "codex-cli": "1.0",
    },
    surface_policies: [{
      surface: "claude-cli", reason: "maintenance",
    }],
    capacity: {
      live_lanes: 3,
      max_worker_lanes: 6,
      summary: "lanes 3/6 · free 8 GB · load 1.5 on 8 cores",
    },
    plan_limits: {
      "codex-cli": {
        plan_tier: "pro",
        windows: [
          windowReading({
            resets_at: new Date(Date.now() + 2.5 * 60 * 60 * 1000).toISOString(),
          }),
          windowReading({
            window_kind: "rolling_7d",
            meter: "secondary",
            remaining_percent: 80,
            resets_at: new Date(Date.now() + 4 * 24 * 60 * 60 * 1000).toISOString(),
          }),
        ],
      },
    },
  }]);

  assert.equal(byClass(host, "machine-card").length, 1);
  assert.equal(
    byClass(host, "machine-capacity-summary")[0].textContent,
    "lanes 3/6 · free 8 GB · load 1.5 on 8 cores",
  );
  assert.equal(
    byClass(host, "machine-capacity-fill")[0].style.width,
    "50.0%",
  );
  assert.deepEqual(
    byClass(host, "machine-surface-name").map((node) => node.textContent),
    ["claude-cli", "codex-cli", "cursor-cli"],
  );
  assert.equal(byClass(host, "machine-limit-row").length, 2);
  assert.equal(byClass(host, "machine-plan-tier")[0].textContent, "pro");
  assert.match(
    byClass(host, "machine-headroom-track")[0].getAttribute("aria-label"),
    /100% is the sustainable-use pivot/,
  );
  assert.equal(byClass(host, "machine-surface-disabled").length, 1);
  assert.equal(byClass(host, "machine-surface-absent").length, 1);
});
