import assert from "node:assert/strict";
import test from "node:test";

import {
  headroomMeterPosition,
  headroomTone,
  laneTone,
  loadTone,
  memoryTone,
  planWindowHeadroom,
  windowLabel,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_machines_meters.js";
import {
  renderMachinesPanel,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_machines_panel.js";
import {
  FakeDocument,
  byClass,
} from "./universe_ui_dom_test_support.mjs";

const NOW = Date.parse("2026-09-04T12:00:00Z");
const GIGABYTE = 1024 * 1024 * 1024;

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

test("a window is labelled by its kind and scope, never its meter id", () => {
  assert.equal(windowLabel(windowReading()), "rolling 5h · all");
  assert.equal(
    windowLabel(windowReading({ window_kind: "rolling_7d", scope: "Fable" })),
    "weekly · Fable",
  );
  assert.equal(
    windowLabel(windowReading({
      window_kind: "monthly", scope: "Cursor Models",
    })),
    "monthly · Cursor Models",
  );
  // An unknown kind still names what it covers rather than the vendor's id.
  assert.equal(
    windowLabel({ window_kind: "unknown", scope: "all", meter: "primary" }),
    "all",
  );
});

test("pressure tones read each fact against what the machine itself has", () => {
  assert.equal(headroomTone(133), "ok");
  assert.equal(headroomTone(94), "warn");
  assert.equal(headroomTone(0), "wall");
  assert.equal(headroomTone(null), "unread");
  assert.equal(memoryTone(2.1 * GIGABYTE, 64 * GIGABYTE), "crit");
  assert.equal(memoryTone(12 * GIGABYTE, 64 * GIGABYTE), "warn");
  assert.equal(memoryTone(24 * GIGABYTE, 64 * GIGABYTE), "ok");
  assert.equal(memoryTone(null, 64 * GIGABYTE), "unknown");
  assert.equal(loadTone(14.2, 18), "warn");
  assert.equal(loadTone(19.1, 18), "crit");
  assert.equal(loadTone(1.8, 18), "ok");
  assert.equal(laneTone(11, 12), "warn");
  assert.equal(laneTone(12, 12), "crit");
  assert.equal(laneTone(2, 12), "ok");
  assert.equal(laneTone(3, null), "unknown");
});

test("a machine card draws capacity and every launchable surface pool", () => {
  const host = renderOneCard({
    machine_id: "machine-1",
    hostname: "studio",
    state: "active",
    liveness: "connected",
    last_seen_at: new Date(Date.now() - 12000).toISOString(),
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
      free_memory_bytes: 8 * GIGABYTE,
      total_memory_bytes: 64 * GIGABYTE,
      load_average_1m: 1.5,
      core_count: 8,
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
  });

  assert.equal(byClass(host, "machine-card").length, 1);
  // One compact row of values, each coloured by its own pressure — not a
  // sentence, and never the raw capacity summary while a cap is published.
  assert.deepEqual(textOf(host, "machine-capacity-fact"), [
    "8.0 GB free", "load 1.5", "lanes 3/6",
  ]);
  assert.deepEqual(
    byClass(host, "machine-capacity-fact").map(
      (node) => node.getAttribute("data-tone"),
    ),
    ["warn", "ok", "ok"],
  );
  assert.equal(byClass(host, "machine-capacity-unreported").length, 0);
  assert.equal(byClass(host, "machine-capacity-fill")[0].style.width, "50.0%");
  assert.equal(byClass(host, "machine-meta")[0].textContent, "active · 12s");
  assert.deepEqual(
    textOf(host, "machine-surface-name"),
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

test("a surface table carries HEADROOM and QUOTA columns and a pivot per bar", () => {
  const host = renderOneCard({
    machine_id: "machine-2",
    hostname: "laptop",
    state: "active",
    liveness: "connected",
    last_seen_at: new Date().toISOString(),
    surface_versions: { "claude-cli": "2.1.259" },
    surface_policies: [],
    capacity: { live_lanes: 11, max_worker_lanes: 12 },
    plan_limits: {
      "claude-cli": {
        plan_tier: "max",
        windows: [
          windowReading({
            remaining_percent: 75,
            resets_at: new Date(Date.now() + 3.75 * 60 * 60 * 1000).toISOString(),
          }),
          windowReading({
            window_kind: "rolling_7d",
            scope: "Fable",
            remaining_percent: 43,
            resets_at: new Date(Date.now() + 20 * 60 * 60 * 1000).toISOString(),
          }),
        ],
      },
    },
  });

  const columns = byClass(host, "machine-limit-columns");
  assert.equal(columns.length, 1);
  assert.deepEqual(
    columns[0].children.map((node) => node.textContent),
    ["headroom", "quota"],
  );
  const rows = byClass(host, "machine-limit-row");
  assert.deepEqual(
    textOf(host, "machine-limit-name"),
    ["rolling 5h · all", "weekly · Fable"],
  );
  // Headroom and quota are two aligned columns, never one sentence.
  assert.deepEqual(textOf(host, "machine-limit-headroom").slice(1), [
    "100%", "361%",
  ]);
  assert.deepEqual(textOf(host, "machine-limit-quota").slice(1), ["75%", "43%"]);
  assert.deepEqual(
    rows.map((node) => node.getAttribute("data-tone")),
    ["ok", "ok"],
  );
  assert.equal(byClass(host, "machine-headroom-pivot").length, 2);
  assert.equal(
    byClass(host, "machine-headroom-pivot")[0].style.left,
    "68%",
  );
});

test("an exhausted pool draws the wall, and an unreadable one says so", () => {
  const host = renderOneCard({
    machine_id: "machine-3",
    hostname: "laptop",
    state: "active",
    liveness: "connected",
    last_seen_at: new Date().toISOString(),
    surface_versions: { "cursor-cli": "2026.09.02" },
    surface_policies: [],
    capacity: {
      live_lanes: 4,
      max_worker_lanes: null,
      summary: "lanes 4/? · capacity unreported (relay_predates_capacity_readings)",
    },
    plan_limits: {
      "cursor-cli": {
        plan_tier: "Ultra",
        windows: [
          windowReading({
            window_kind: "monthly",
            scope: "Cursor Models",
            remaining_percent: 0,
            resets_at: new Date(Date.now() + 12 * 24 * 60 * 60 * 1000).toISOString(),
          }),
          {
            status: "unknown",
            window_kind: "unknown",
            scope: "all",
            meter: "unknown",
            remaining_percent: null,
            resets_at: null,
            reason: "stale_credential",
          },
        ],
      },
    },
  });

  const rows = byClass(host, "machine-limit-row");
  assert.deepEqual(
    rows.map((node) => node.getAttribute("data-tone")),
    ["wall", "unread"],
  );
  assert.deepEqual(textOf(host, "machine-limit-headroom").slice(1), [
    "wall", "—",
  ]);
  assert.deepEqual(textOf(host, "machine-limit-quota").slice(1), ["0%", "—"]);
  // The wall keeps the scale it is measured against; an unreadable window has
  // no reading to place against one, so it carries neither fill nor pivot.
  assert.equal(byClass(host, "machine-headroom-pivot").length, 1);
  assert.equal(byClass(host, "machine-headroom-fill").length, 1);
  assert.match(
    byClass(host, "machine-headroom-track")[0].getAttribute("aria-label"),
    /at the wall/,
  );
  assert.equal(byClass(host, "machine-limit-name")[1].textContent, "no reading");
  assert.match(
    byClass(host, "machine-limit-note")[0].textContent,
    /stale_credential — launches still attempt and fail/,
  );
  // No published cap means no bar, and the relay's own reason stays visible.
  assert.equal(byClass(host, "machine-capacity-fill").length, 0);
  assert.match(
    byClass(host, "machine-capacity-unreported")[0].textContent,
    /capacity unreported/,
  );
  assert.deepEqual(textOf(host, "machine-capacity-fact"), [
    "unknown free", "load unknown", "lanes 4/?",
  ]);
});
