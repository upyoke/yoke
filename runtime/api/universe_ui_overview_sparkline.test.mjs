/**
 * Momentum sparkline encoding — what the line says about a quiet day.
 *
 * These series are heavy-tailed by nature: one vendored bulk commit or one
 * mass doc rewrite can be many times the median day. The encoding has to
 * survive that shape, because the distinction it exists to carry is between
 * a day where something happened and a day where nothing did.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

import { overviewClient } from "./universe_ui_overview_view_test_support.mjs";

const BASELINE_Y = 25;

function heavyTailedVitals() {
  const day = (value) => ({
    activity: value, code: value, issues: value, strategy: value,
  });
  return {
    state_counts: {
      active: 0, pipeline: 0, backlog: 0, blocked: 0, frozen: 0, done: 0,
    },
    momentum: [
      { day: "2026-07-24", ...day(0) },
      { day: "2026-07-25", ...day(1) },
      { day: "2026-07-26", ...day(5000) },
    ],
    zen: [],
    streak_days: 0,
    lifetime_pct: null,
    project_days: 0,
    days: 3,
  };
}

function seriesHeights(root) {
  return byClass(root, "overview-sparkline-line").map((line) => ({
    series: line.attributes.get("data-series"),
    heights: line.attributes.get("points")
      .split(" ")
      .map((pair) => Number(pair.split(",")[1])),
  }));
}

test("a day with activity never renders on the zero baseline", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");

  const mounted = mountUniverseApp(root, {
    client: overviewClient({ "overview.vitals.get": heavyTailedVitals() }),
  });
  await settle();

  const lines = seriesHeights(root);
  assert.deepEqual(
    lines.map((line) => line.series),
    ["activity", "code", "issues", "strategy"],
  );
  for (const { series, heights } of lines) {
    const [empty, quiet, busiest] = heights;
    assert.equal(empty, BASELINE_Y, `${series}: an empty day belongs on the baseline`);
    assert.ok(
      quiet < BASELINE_Y,
      `${series}: a day with real work must clear the baseline, got y=${quiet}`,
    );
    assert.ok(
      busiest < quiet,
      `${series}: the busiest day must still outrank a quiet one`,
    );
  }
  mounted.unmount();
});
