import assert from "node:assert/strict";
import test from "node:test";
import { drawPerformanceChart, SERIES } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_performance_chart.js";
import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";

test("hover, toggles, bucket inspection and disposal preserve raw spike values", async (t) => {
  const document = new FakeDocument(), parent = document.createElement("section");
  const host = document.createElement("div"); parent.appendChild(host);
  host.clientWidth = 800;
  host.after = node => parent.appendChild(node);
  let plot;
  class Plot {
    constructor(options, data) {
      Object.assign(this, { options, data, series: options.series,
        cursor: { idx: null, left: 80, top: 90 }, over: document.createElement("div") });
      plot = this;
    }
    setSeries(index, value) { Object.assign(this.series[index], value); }
    setCursor(value) { Object.assign(this.cursor, value); this.options.hooks.setCursor[0](this); }
    valToPos() { return 30; }
    setSize() {}
    destroy() { this.destroyed = true; }
  }
  const oldStyle = globalThis.getComputedStyle, oldObserver = globalThis.ResizeObserver;
  globalThis.getComputedStyle = () => ({ getPropertyValue: () => "#777" });
  globalThis.ResizeObserver = class { observe() {} disconnect() {} };
  t.after(() => { globalThis.getComputedStyle = oldStyle; globalThis.ResizeObserver = oldObserver; });
  const metrics = Object.fromEntries(SERIES.map(([family]) => [family, {
    avg_ms: 100, p95_ms: 427424, count: 8, timed_count: 8, resolution_seconds: 300,
  }]));
  const bucket = { start: 1791378000, end: 1791378300, metrics }, inspected = [];
  const dispose = await drawPerformanceChart({ documentNode: document, host,
    result: { buckets: [bucket] }, inspect: value => inspected.push(value), Plot });
  assert.equal(plot.options.scales.y.distr, 4);
  assert.equal(plot.data[2][0], 427424);
  assert.equal(plot.series[3].show, false);
  assert.equal(plot.series[6].show, false);
  plot.over.dispatchEvent(new Event("click"));
  assert.equal(inspected.length, 0, "no cursor means no accidental first-bucket inspection");
  plot.cursor.idx = 0; plot.options.hooks.setCursor[0](plot);
  const tip = byClass(host, "performance-hover")[0];
  tip.remove = () => tip.parentNode.removeChild(tip);
  assert.equal(tip.hidden, false);
  assert.match(tip.textContent, /427.42s/);
  assert.match(tip.textContent, /Click to inspect observations/);
  assert.doesNotMatch(tip.textContent, /Watcher/);
  const toggles = byClass(parent, "performance-series")[0];
  toggles.remove = () => toggles.parentNode.removeChild(toggles);
  toggles.children[5].dispatchEvent(new Event("click"));
  assert.equal(plot.series[6].show, true);
  assert.equal(toggles.children[5].getAttribute("aria-pressed"), "true");
  plot.options.hooks.setCursor[0](plot);
  assert.match(tip.textContent, /Watcher/);
  plot.over.dispatchEvent(new Event("click"));
  assert.equal(inspected[0], bucket);
  plot.over.dispatchEvent(new Event("mouseleave"));
  assert.equal(tip.hidden, true);
  dispose(); assert.equal(plot.destroyed, true);
});
