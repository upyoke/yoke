import assert from "node:assert/strict";
import test from "node:test";
import { NAV, buildUniverseRoute, parseUniverseRoute } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_navigation.js";
import { createPathNavigation, ROUTE_NAVIGATION_EVENT } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_path_navigation.js";
import { createSelectionNavigation } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_selection_routes.js";
import { createProjectSelection } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_project_selection.js";
import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { FakeDocument, byClass, response, settle } from "./universe_ui_dom_test_support.mjs";
import { threeProjectClient, scopeChips } from "./universe_ui_read_views_test_support.mjs";

import { workflowsClient, workflowFixture } from "./universe_ui_workflows_test_support.mjs";

const BASE = "/orgs/acme";

test("every destination builds and parses beneath either mount base", () => {
  for (const base of ["", BASE]) for (const { id } of NAV) {
    const href = buildUniverseRoute(id, "1,2", null, null, base);
    assert.equal(href, `${base}/${id}?project=1,2`);
    assert.equal(parseUniverseRoute(href, base).view, id);
  }
  const detail = "flow/name with spaces";
  const href = buildUniverseRoute("deployments", "1", "flows", detail, BASE);
  assert.deepEqual(parseUniverseRoute(href, BASE), {
    view: "deployments", tab: "flows", detail, project: "1", selection: null,
  });
  assert.throws(() => buildUniverseRoute("items", null, null, null, "//elsewhere"),
    /dashboard_base_path_invalid/);
});

test("legacy entry replaces the fragment once, preserving detail and its query", () => {
  const window = new FakeDocument().defaultView;
  window.location.href = `${BASE}#/deployments/runs/run-id?project=2&selection=1,2`;
  const history = window.history;
  let replaces = 0, pushes = 0;
  const replace = history.replaceState;
  history.replaceState = (...args) => { replaces++; replace(...args); };
  const push = history.pushState;
  history.pushState = (...args) => { pushes++; push(...args); };
  createPathNavigation(window, BASE);
  assert.equal(window.location.href, `${BASE}/deployments/runs/run-id?project=2&selection=1,2`);
  assert.equal(window.location.hash, "");
  assert.equal(pushes, 0);
  assert.equal(replaces, 2); // URL conversion and ancestry stamp, no new entry.
  assert.deepEqual(window.scrollCalls, []);
});

test("Back/Forward restore the exact route without scrolling or adding entries", () => {
  const window = new FakeDocument().defaultView;
  window.location.href = `${BASE}/items?project=1`;
  const paths = createPathNavigation(window, BASE);
  let renders = 0;
  window.addEventListener(ROUTE_NAVIGATION_EVENT, () => renders++);
  paths.navigate("/shipping?project=2");
  paths.navigate("/deployments/flows/first?project=2");
  assert.equal(renders, 2);
  assert.equal(window.scrollCalls.length, 2);
  window.history.back();
  assert.equal(paths.current(), `${BASE}/shipping?project=2`);
  window.history.forward();
  assert.equal(paths.current(), `${BASE}/deployments/flows/first?project=2`);
  assert.equal(window.scrollCalls.length, 2);
  assert.equal(renders, 2);
});

test("project-switch navigation starts at top, canonical replacement does not", () => {
  const window = new FakeDocument().defaultView;
  const paths = createPathNavigation(window);
  paths.replace("/items?project=all");
  assert.deepEqual(window.scrollCalls, []);
  paths.navigate("/items?project=2", { projectSwitch: true });
  assert.deepEqual(window.scrollCalls, [[0, 0]]);
  paths.navigate("/items?project=2");
  assert.equal(window.scrollCalls.length, 1);
});

test("Flows Back uses app history, including after remount, or navigates to list", () => {
  const window = new FakeDocument().defaultView;
  window.location.href = `${BASE}/deployments/flows/first`;
  let paths = createPathNavigation(window, BASE);
  paths.back("/deployments/flows");
  assert.equal(paths.current(), `${BASE}/deployments/flows`);
  paths.navigate("/deployments/flows/second");
  paths = createPathNavigation(window, BASE);
  paths.back("/deployments/flows");
  assert.equal(paths.current(), `${BASE}/deployments/flows`);
  window.history.forward();
  assert.equal(paths.current(), `${BASE}/deployments/flows/second`);
});

test("copied host links are qualified and modified clicks retain browser handling", () => {
  const document = new FakeDocument(), window = document.defaultView;
  window.location.href = `${BASE}/items`;
  const root = document.createElement("div"), anchor = document.createElement("a");
  root.appendChild(anchor);
  anchor.setAttribute("href", "/strategy/PLAN?project=1");
  anchor.closest = () => anchor;
  root.querySelectorAll = () => [anchor];
  const state = createProjectSelection(null);
  state.seed("strategy", ["1", "2"]);
  const handlers = [];
  root.addEventListener = (type, handler) => { if (type === "click") handlers.push(handler); };
  const navigation = createSelectionNavigation(root, window, state, BASE);
  navigation.refresh();
  assert.equal(anchor.getAttribute("href"), `${BASE}/strategy/PLAN?project=1&selection=1,2`);
  let prevented = false;
  anchor.hasAttribute = () => false;
  const event = { type: "click", target: anchor, button: 0,
    preventDefault() { prevented = true; }, ctrlKey: true };
  for (const handler of handlers) handler(event);
  assert.equal(prevented, false);
  event.ctrlKey = false;
  for (const handler of handlers) handler(event);
  assert.equal(prevented, true);
  assert.equal(window.location.pathname, `${BASE}/strategy/PLAN`);
  navigation.dispose();
});

test("mounted project chips and browser history use the same scoped route", async (t) => {
  const prior = globalThis.fetch;
  globalThis.fetch = () => response(200, {});
  t.after(() => { globalThis.fetch = prior; });
  const document = new FakeDocument(), window = document.defaultView;
  window.location.href = `${BASE}/items?project=1`;
  const root = document.createElement("div");
  const mounted = mountUniverseApp(root, { client: threeProjectClient(), basePath: BASE });
  t.after(() => mounted.unmount());
  await settle();
  const chip = scopeChips(root).find(node => node.textContent === "BET");
  chip.dispatchEvent(new Event("click"));
  await settle();
  assert.equal(window.location.href, `${BASE}/items?project=1,2`);
  assert.deepEqual(window.scrollCalls, [[0, 0]]);
  window.history.back();
  await settle();
  assert.equal(window.location.href, `${BASE}/items?project=1`);
  assert.deepEqual(window.scrollCalls, [[0, 0]]);
  assert.ok(byClass(root, "scope-bar").length);
});

test("hosted workflow picks replace the current entry so Back skips selections", async (t) => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = () => response(200, {});
  t.after(() => { globalThis.fetch = previousFetch; });
  const document = new FakeDocument(), window = document.defaultView;
  window.location.href = `${BASE}/items`;
  createPathNavigation(window, BASE).navigate("/workflows/dash");
  const entries = new Map([["yoke:item-draft:obsolete", "discard"], ["yoke:item-draft-base:current", "keep"]]);
  window.sessionStorage = {
    get length() { return entries.size; }, key: index => [...entries.keys()][index],
    removeItem: key => entries.delete(key),
  };
  const root = document.createElement("div");
  const client = workflowsClient([workflowFixture({ id: "dash", name: "Dash" }), workflowFixture({ id: "blitz", name: "Blitz" })]);
  const mounted = mountUniverseApp(root, { client, basePath: BASE });
  assert.deepEqual([...entries], [["yoke:item-draft-base:current", "keep"]]);
  t.after(() => mounted.unmount());
  await settle();
  byClass(root, "tab-link").find(node => node.textContent === "Blitz").dispatchEvent(new Event("click"));
  assert.equal(window.location.href, `${BASE}/workflows/blitz?selection=all`);
  assert.equal(byClass(root, "tab-link").find(node => node.getAttribute("aria-selected") === "true").textContent, "Blitz");
  assert.equal(window.scrollCalls.length, 2);
  window.history.back();
  assert.equal(window.location.pathname, `${BASE}/items`);
  window.history.forward();
  assert.equal(window.location.href, `${BASE}/workflows/blitz?selection=all`);
  assert.equal(window.scrollCalls.length, 2); // Entering workflows and selecting it.
});

for (const basePath of ["", BASE]) for (const eventType of ["click", "keydown"]) {
  test(`row activation uses shared history at ${basePath || "root"} via ${eventType}`, async (t) => {
    const prior = globalThis.fetch;
    globalThis.fetch = () => response(200, {});
    t.after(() => { globalThis.fetch = prior; });
    for (const view of ["items", "capabilities"]) {
      const document = new FakeDocument(), window = document.defaultView;
      window.location.href = `${basePath}/${view}?project=1`;
      const baseClient = threeProjectClient();
      const client = { call: (request) => request.function === "projects.capabilities.list"
        ? Promise.resolve({ status: 200, envelope: { success: true, result: { rows: [{
          project_id: 1, type: "test-machine", display_label: "Test machine",
          detail_view: "test-machine", state: "configured_unverified",
        }] } } }) : baseClient.call(request) };
      const root = document.createElement("div");
      const mounted = mountUniverseApp(root, { client, basePath });
      t.after(() => mounted.unmount());
      await settle();
      const row = byClass(root, view === "items" ? "item-roster-row" : "capability-route-row")[0];
      const event = new Event(eventType, { cancelable: true });
      if (eventType === "keydown") Object.defineProperty(event, "key", { value: "Enter" });
      row.dispatchEvent(event);
      assert.ok(window.location.pathname.startsWith(`${basePath}/${view}/`));
      assert.equal(window.history.state.yokeDashboard.position, 1);
      window.history.back();
      assert.equal(window.location.pathname, `${basePath}/${view}`);
    }
  });
}
