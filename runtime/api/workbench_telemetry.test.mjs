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
const preferences = new Map();
browser.localStorage = {
  getItem: key => preferences.get(key),
  setItem: (key, value) => preferences.set(key, value),
  removeItem: key => preferences.delete(key),
};
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
  if (url.endsWith("/attribution")) return Response.json(
    options.method === "DELETE" ? { cleared: true } : record,
  );
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

test("workbench consent emits one initial view and one per URL navigation, then revokes", async () => {
  const root = doc.createElement("div");
  const originalPush = history.pushState;
  const originalReplace = history.replaceState;
  const cleanup = mountWorkbenchTelemetry(root, browser);
  const control = byClass(root, "workbench-telemetry")[0];
  const button = control.children[0];
  await until(() => !button.disabled);
  assert.equal(requests.length, 1); // Configuration is public; no denied capture.
  assert.equal(preferences.size, 0);
  assert.equal(events.length, 0);
  button.dispatchEvent(new Event("click"));
  await until(async () => { await flushEvents(); return events.length === 1 && !button.disabled; });
  assert.equal(button.getAttribute("aria-pressed"), "true");
  assert.equal(events[0].page_url, "https://workbench.example/items?utm_source=email");
  assert.equal(events[0].visitor_id, record.visitor_id);
  assert.equal(events[0].event_type, "page_view");
  assert.equal(events[0].referrer, null);
  history.pushState({}, "", "/sessions");
  history.replaceState({}, "", "/sessions?tab=active");
  location = new URL("https://workbench.example/items");
  browser.dispatchEvent(new Event("popstate"));
  history.replaceState({ stateOnly: true }, "", location.href);
  await until(async () => { await flushEvents(); return events.length === 4; });
  assert.deepEqual(events.map(e => e.page_path), ["/items", "/sessions", "/sessions", "/items"]);
  assert.equal(new Set(events.map(e => e.event_id)).size, 4);
  assert.equal(events[1].referrer, events[0].page_url);
  assert.ok(events.every(e => !e.page_url.includes("token")));
  button.dispatchEvent(new Event("click"));
  await until(() => !button.disabled);
  assert.equal(button.getAttribute("aria-pressed"), "false");
  assert.equal(preferences.size, 0);
  assert.equal(requests.at(-1).method, "DELETE");
  history.pushState({}, "", "/strategy");
  await flushEvents();
  assert.equal(events.length, 4);
  cleanup();
  assert.equal(history.pushState, originalPush);
  assert.equal(history.replaceState, originalReplace);
  assert.equal(root.children.length, 0);
  assert.equal(doc.head.children.length, 0);
});

test("unavailable configuration names the recovery and leaves the workbench mounted", async () => {
  configFailure = true;
  const root = doc.createElement("div");
  const warnings = [], originalWarn = console.warn;
  console.warn = (...args) => warnings.push(args.join(" "));
  const cleanup = mountWorkbenchTelemetry(root, browser);
  try {
    const status = byClass(root, "workbench-telemetry")[0].children[1];
    await until(() => status.textContent);
    assert.match(status.textContent, /Analytics unavailable\. Reload to retry/);
    assert.match(warnings[0], /collector_setup_failed/);
  } finally { cleanup(); console.warn = originalWarn; }
});
