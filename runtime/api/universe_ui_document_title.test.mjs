import assert from "node:assert/strict";
import test from "node:test";
import { FakeDocument } from "./universe_ui_dom_test_support.mjs";

// The page-view tracker reads browser globals, so this file runs the real
// history owner and the real tracker against one fake window.
const doc = new FakeDocument();
const browser = doc.defaultView;
Object.assign(browser, { screen: { width: 1920, height: 1080 }, innerWidth: 1200, innerHeight: 800 });
doc.referrer = "";
globalThis.window = browser;
globalThis.document = doc;
globalThis.history = browser.history;
Object.defineProperty(globalThis, "navigator", {
  value: { userAgent: "WorkbenchBrowser", language: "en-US" }, configurable: true,
});
const events = [];
globalThis.fetch = async (url, options = {}) => {
  if (url.endsWith("/attribution")) return Response.json({ visitor_id: crypto.randomUUID() });
  const batch = JSON.parse(options.body).events;
  events.push(...batch);
  return Response.json({ accepted: batch.length });
};
const static_ = "../../packages/yoke-core/src/yoke_core/ui/static";
const { parseUniverseRoute, routeDocumentTitle } = await import(`${static_}/universe_navigation.js`);
const { createPathNavigation } = await import(`${static_}/universe_path_navigation.js`);
const { configureEvents, flushEvents } = await import(`${static_}/events.js`);
const { startPageViews } = await import(`${static_}/events_navigation.js`);

const titleOf = (href) => routeDocumentTitle(parseUniverseRoute(href));
const settled = async (count) => {
  const deadline = performance.now() + 5000;
  while (events.length < count) {
    assert.ok(performance.now() < deadline, "page_view_timeout: expected page views to send");
    await new Promise(setImmediate);
    await flushEvents();
  }
};

test("each screen's title names it, most specific part first", () => {
  assert.equal(titleOf("/frontier"), "Frontier · Yoke");
  assert.equal(titleOf("/levels"), "Levels · Yoke");
  assert.equal(titleOf("/items/YOK-3892?selection=1"), "YOK-3892 · Items · Yoke");
  assert.equal(titleOf("/deployments/runs"), "Runs · Deployments · Yoke");
  assert.equal(titleOf("/deployments/flows/name%20here"), "name here · Flows · Deployments · Yoke");
  assert.equal(titleOf("/machine-approval/ABCD-1234"), "Connect your machine · Yoke");
});

test("navigation names the screen before page views read the title", async () => {
  browser.location.href = "/frontier?project=1";
  const paths = createPathNavigation(browser);
  assert.equal(doc.title, "Frontier · Yoke");
  configureEvents({ publishableKey: "public", endpoint: "/api/events", attributionEndpoint: "/api/events/attribution" });
  const stop = startPageViews();
  try {
    paths.navigate("/items/YOK-3892?selection=1");
    assert.equal(doc.title, "YOK-3892 · Items · Yoke");
    browser.history.back();
    assert.equal(doc.title, "Frontier · Yoke");
    await settled(3);
  } finally { stop(); paths.dispose(); }
  assert.deepEqual(events.map((event) => event.page_title),
    ["Frontier · Yoke", "YOK-3892 · Items · Yoke", "Frontier · Yoke"]);
  assert.deepEqual(events.map((event) => event.page_path), ["/frontier", "/items/YOK-3892", "/frontier"]);
});
