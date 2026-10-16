import assert from "node:assert/strict";
import test from "node:test";

import {
  renderMachinesPanel,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_machines_panel.js";
import {
  FakeDocument,
  byClass,
} from "./universe_ui_dom_test_support.mjs";

// The server composes the extra-usage phrase with the rule that decides
// launches and wakes; the card prints it under the included windows.
function render(reading) {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("div");
  renderMachinesPanel({ document: documentNode }, host, [{
    machine_id: "machine-1",
    hostname: "laptop",
    state: "active",
    liveness: "connected",
    last_seen_at: new Date().toISOString(),
    surface_versions: { "codex-cli": "0.148" },
    surface_policies: [],
    capacity: { live_lanes: 0, max_worker_lanes: 4, summary: "lanes 0/4" },
    plan_limits: {
      "codex-cli": {
        plan_tier: "pro",
        windows: [{
          status: "ok",
          window_kind: "rolling_7d",
          scope: "all",
          meter: "primary",
          remaining_percent: 0,
          resets_at: new Date(Date.now() + 86400000).toISOString(),
        }],
        ...reading,
      },
    },
  }], {});
  return byClass(host, "machine-limit-extra");
}

test("an empty included window shows the extra usage that keeps it running", () => {
  const rows = render({
    observed_at: new Date().toISOString(),
    extra_usage_status: "available",
    extra_usage_label: "extra usage available (balance 61,206.81 Codex credits)",
  });
  assert.equal(rows.length, 1);
  assert.equal(
    rows[0].textContent,
    "extra usage available (balance 61,206.81 Codex credits)",
  );
  assert.equal(rows[0].getAttribute("data-status"), "available");
});

test("a stale reading says so instead of showing an old balance", () => {
  const rows = render({
    observed_at: new Date(Date.now() - 3600000).toISOString(),
    extra_usage_status: "available",
    extra_usage_label: "extra usage available (balance 61,206.81 Codex credits)",
  });
  assert.equal(rows[0].textContent, "extra usage reading stale");
  assert.equal(rows[0].getAttribute("data-status"), "stale");
});

test("a server that predates extra usage draws no extra-usage line", () => {
  assert.equal(render({ observed_at: new Date().toISOString() }).length, 0);
});
