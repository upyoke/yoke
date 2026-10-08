import assert from "node:assert/strict";
import test from "node:test";
import { renderPerformanceView, validateRange, localInput, WINDOWS } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_performance.js";
import { chartData, SERIES } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_performance_chart.js";
import { NAV } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_destinations.js";
import { FakeDocument, byClass, settle } from "./universe_ui_dom_test_support.mjs";

test("Performance inherits the current multiple-project selector contract", () => {
  const destination = NAV.find(v => v.id === "performance");
  assert.equal(destination.scope, "multi");
  assert.equal(destination.group, "diagnostics");
});
test("date ranges reject reversal and serialize unambiguous timestamps", () => {
  assert.throws(() => validateRange("invalid", "2026-10-08T12:00"), /range_invalid/);
  assert.throws(() => validateRange("2026-10-08T12:00", "2026-10-08T11:00"), /range_invalid/);
  const range = validateRange("2026-10-08T11:00", "2026-10-08T12:00");
  assert.match(range.since, /Z$/);
  assert.equal(Date.parse(range.until) - Date.parse(range.since), 3600000);
  assert.equal(localInput("2026-10-08T11:00").length, 16);
  assert.deepEqual(WINDOWS.map(([hours]) => hours), [1, 12, 24, 72, 168, 720]);
});
test("sparse observations and unknowns are retained on their own axes", () => {
  const metrics = Object.fromEntries(["function", "tool", "hook", "relay", "watcher"].map(f => [f, { avg_ms: null, p95_ms: null }]));
  const result = { buckets: [{ start: 1, metrics }, { start: 2, metrics: { ...metrics, watcher: { avg_ms: 10000, p95_ms: 10000 } } }] };
  const data = chartData(result);
  assert.equal(data.length, SERIES.length + 2);
  assert.deepEqual(data[6], [null, 10000]);
  assert.equal(SERIES[5][4], "wait");
  assert.equal(SERIES[0][4], undefined);
  assert.deepEqual(data.at(-1), [2000, 2000]);
});

test("scope changes abort reads and discard late data from the previous scope", async () => {
  const document = new FakeDocument(), main = document.createElement("main");
  const calls = [];
  const client = { call: (request, init) => new Promise(resolve => calls.push({ request, init, resolve })) };
  const oldRoute = new AbortController();
  renderPerformanceView({ document, client, signal: oldRoute.signal }, main, ["11", "12"]);
  assert.deepEqual(calls[0].request.payload.project_ids, [11, 12]);
  oldRoute.abort();
  renderPerformanceView({ document, client, signal: new AbortController().signal }, main, "all");
  assert.equal(calls[0].init.signal.aborted, true);
  assert.equal(calls[1].request.payload.project_ids, null);
  const result = marker => ({ envelope: { success: true, result: {
    buckets: [], observation_count: 0, bucket_seconds: 300, last_observation: null,
    queried_at: new Date().toISOString(), coverage: marker,
  } } });
  calls[1].resolve(result("Current universe coverage"));
  await settle();
  calls[0].resolve(result("Forbidden stale coverage"));
  await settle();
  assert.match(main.textContent, /Current universe coverage/);
  assert.doesNotMatch(main.textContent, /Forbidden stale coverage/);
  assert.match(main.textContent, /Unknown/);
});

test("invalid custom ranges refuse without a read and presets resynchronize both fields", async () => {
  const document = new FakeDocument(), main = document.createElement("main"), calls = [];
  renderPerformanceView({ document, client: { call: request => {
    calls.push(request); return new Promise(() => {});
  } }, signal: new AbortController().signal }, main, "all");
  const dates = byClass(main, "performance-dates")[0];
  const [from, to] = dates.children.map(label => label.children[0]);
  from.value = to.value;
  from.dispatchEvent(new Event("change"));
  assert.equal(calls.length, 1);
  assert.match(main.textContent, /performance_range_invalid/);
  const hour = byClass(main, "performance-windows")[0].children[0];
  hour.dispatchEvent(new Event("click"));
  assert.equal(calls.length, 2);
  assert.equal(Date.parse(to.value) - Date.parse(from.value), 3600000);
  assert.equal(hour.getAttribute("aria-pressed"), "true");
});


test("Custom is an actionable range control that keeps dates and focuses From", () => {
  const document = new FakeDocument(), main = document.createElement("main");
  renderPerformanceView({ document, client: { call: () => new Promise(() => {}) },
    signal: new AbortController().signal }, main, "all");
  const custom = byClass(main, "performance-custom")[0];
  const from = byClass(main, "performance-dates")[0].children[0].children[0];
  const before = from.value;
  assert.equal(custom.tagName, "BUTTON");
  custom.dispatchEvent(new Event("click"));
  assert.equal(custom.getAttribute("aria-pressed"), "true");
  assert.equal(from.value, before);
  assert.equal(document.activeElement, from);
});
