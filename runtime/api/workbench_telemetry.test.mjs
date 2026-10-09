import assert from "node:assert/strict";
import test from "node:test";
import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";

const doc = new FakeDocument();
doc.title = "Workbench";
doc.referrer = "";
let location = new URL("https://workbench.example/items?token=door&utm_source=email");
const browser = Object.assign(new EventTarget(), {
  innerWidth: 1200,
  history: {
    pushState(_state, _title, url) { if (url) location = new URL(url, location); },
    replaceState(_state, _title, url) { if (url) location = new URL(url, location); },
  },
});
Object.defineProperty(browser, "location", { get: () => location });
globalThis.window = browser;
globalThis.history = browser.history;
globalThis.document = doc;
Object.defineProperty(globalThis, "navigator", {
  value: { userAgent: "WorkbenchBrowser" }, configurable: true,
});
const requests = [], events = [];
let configFailure = false;
const record = {
  visitor_id: crypto.randomUUID(),
  first_touch: { acquisition_channel: "email" },
  last_touch: { acquisition_channel: "email" },
};
browser.fetch = globalThis.fetch = async (url, options = {}) => {
  requests.push({ url, ...options });
  if (url.endsWith("/config")) return Response.json(
    configFailure ? { error: "collector_unavailable" } : { publishableKey: "public" },
    { status: configFailure ? 503 : 200 },
  );
  assert.equal(options.headers["X-Events-Key"], "public");
  if (url.endsWith("/attribution")) return Response.json(record);
  const batch = JSON.parse(options.body).events;
  events.push(...batch);
  return Response.json({ accepted: batch.length });
};
const { mountWorkbenchTelemetry } = await import(
  "../../packages/yoke-core/src/yoke_core/ui/static/workbench_telemetry.js"
);
const { flushEvents } = await import(
  "../../packages/yoke-core/src/yoke_core/ui/static/events.js"
);
const until = async condition => {
  const deadline = performance.now() + 5000;
  while (!await condition()) {
    assert.ok(performance.now() < deadline, "telemetry_timeout: expected work to finish");
    await new Promise(setImmediate);
  }
};

test("workbench collects one initial view and one per path change with no consent step", async () => {
  const originalPush = history.pushState;
  const originalReplace = history.replaceState;
  const cleanup = mountWorkbenchTelemetry(browser);
  await until(async () => { await flushEvents(); return events.length === 1; });
  assert.equal(requests[0].url, "/api/events/config");
  assert.equal(events[0].page_url, "https://workbench.example/items?utm_source=email");
  assert.equal(events[0].visitor_id, record.visitor_id);
  assert.equal(events[0].event_type, "page_view");
  assert.equal(events[0].referrer, null);
  history.pushState({}, "", "/sessions");
  // Query-only rewrites (filters, ?selection=all) are not new pages.
  history.replaceState({}, "", "/sessions?tab=active");
  history.replaceState({}, "", "/sessions?selection=all");
  location = new URL("https://workbench.example/items");
  browser.dispatchEvent(new Event("popstate"));
  history.replaceState({ stateOnly: true }, "", location.href);
  await until(async () => { await flushEvents(); return events.length === 3; });
  assert.deepEqual(events.map(e => e.page_path), ["/items", "/sessions", "/items"]);
  assert.equal(new Set(events.map(e => e.event_id)).size, 3);
  assert.equal(events[1].referrer, events[0].page_url);
  assert.ok(events.every(e => !e.page_url.includes("token")));
  cleanup();
  assert.equal(history.pushState, originalPush);
  assert.equal(history.replaceState, originalReplace);
  history.pushState({}, "", "/strategy");
  await flushEvents();
  assert.equal(events.length, 3);
});

test("unavailable configuration names the recovery and leaves the workbench mounted", async () => {
  configFailure = true;
  const warnings = [], originalWarn = console.warn;
  console.warn = (...args) => warnings.push(args.join(" "));
  const cleanup = mountWorkbenchTelemetry(browser);
  try {
    await until(() => warnings.length);
    assert.match(warnings[0], /collector_setup_failed/);
  } finally { cleanup(); console.warn = originalWarn; }
});
