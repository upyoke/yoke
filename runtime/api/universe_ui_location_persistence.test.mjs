import { createPathNavigation } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_path_navigation.js";
import assert from "node:assert/strict";
import test from "node:test";
import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { createLocationPreference, locationResolves } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_location_preference.js";
import { createProjectSelection } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_project_selection.js";
import { FakeDocument, byClass, response, settle } from "./universe_ui_dom_test_support.mjs";
import { twoProjectClient } from "./universe_ui_read_views_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });
const projects = [{ id: 1 }, { id: 2 }];

function preferenceClient(state = { views: {}, last_location: null }) {
  const base = twoProjectClient();
  return {
    state, requests: base.requests,
    async call(request) {
      if (request.function === "ui_preferences.screen_selection.list") {
        base.requests.push(request);
        return ok({ ...state });
      }
      if (request.function === "ui_preferences.screen_selection.set") {
        base.requests.push(request);
        const { view_id, selection, focus, location } = request.payload;
        if (location !== undefined) state.last_location = location;
        else state.views[view_id] = { selection, focus };
        return ok({});
      }
      return base.call(request);
    },
  };
}

async function mountAt(t, hash, client, basePath = "") {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = () => response(200, {});
  t.after(() => { globalThis.fetch = originalFetch; });
  const documentNode = new FakeDocument();
  const windowNode = documentNode.defaultView;
  windowNode.fetch = () => response(503, {});
  windowNode.location.href = hash || "/";
  windowNode.history = { replaceState(_state, _title, route) { windowNode.location.href = route; } };
  const root = documentNode.createElement("div");
  const app = mountUniverseApp(root, { client, basePath });
  t.after(() => app.unmount());
  await settle();
  return { root, windowNode, app, async navigate(route) {
    windowNode.location.href = route;
    windowNode.dispatchEvent(new Event("popstate"));
    await settle();
  } };
}

test("a fresh mount and a new tab restore the actor's last page with its query", async (t) => {
  const client = preferenceClient();
  const first = await mountAt(t, "/sessions?project=1", client);
  await first.navigate("/items?project=2&return=workflows");
  const saved = client.state.last_location;
  assert.equal(saved, "/items?return=workflows&project=2");
  first.app.unmount();
  // A new client bound to the same actor's persisted preference represents
  // the sign-in/new-tab boundary; no browser state is shared.
  const next = await mountAt(t, "", preferenceClient(client.state));
  assert.equal(next.windowNode.location.href, saved);
  assert.match(next.root.textContent, /Items/);
});

test("an explicit deep link or explicit default page wins and becomes the preference", async (t) => {
  for (const hash of ["/items?project=1", "/strategy?project=all"]) {
    const client = preferenceClient({ views: {}, last_location: "/sessions?project=2" });
    const mounted = await mountAt(t, hash, client);
    assert.equal(mounted.windowNode.location.href, hash);
    assert.equal(client.state.last_location, hash);
    mounted.app.unmount();
  }
});

test("invalid saved locations silently fall back to the current default page", async (t) => {
  for (const saved of ["/removed", "/items?project=removed", "/items/%ZZ?project=1", "/actors/unknown"]) {
    const client = preferenceClient({ views: {}, last_location: saved });
    const mounted = await mountAt(t, "", client);
    assert.equal(mounted.windowNode.location.href, "/strategy?project=all");
    assert.equal(client.state.last_location, "/strategy?project=all");
    assert.doesNotMatch(byClass(mounted.root, "content")[0].textContent, /unavailable|not found|read failed/);
    mounted.app.unmount();
  }
});

test("a removed or denied item falls back before its detail renderer runs", async (t) => {
  for (const code of ["item_not_found", "access_denied"]) {
    const client = preferenceClient({ views: {}, last_location: "/items/missing?project=1&selection=all" });
    const baseCall = client.call.bind(client);
    client.call = async (request) => request.function === "items.detail.get"
      ? { status: 200, envelope: { success: false, error: { code } } }
      : baseCall(request);
    const mounted = await mountAt(t, "", client);
    assert.equal(mounted.windowNode.location.href, "/strategy?project=all");
    assert.doesNotMatch(byClass(mounted.root, "content")[0].textContent, /read failed/);
    mounted.app.unmount();
  }
});

test("a saved detail resolves through the accessible resource authority", async () => {
  const requests = [];
  const client = { async call(request) { requests.push(request); return ok({ item: { public_ref: "example" } }); } };
  assert.equal(await locationResolves(client, "/items/example?project=2&selection=all", projects), true);
  assert.deepEqual(requests[0].target, { kind: "item", public_ref: "example", project_id: "2" });
  assert.equal(await locationResolves(client, "/items/example?project=gone", projects), false);
  assert.equal(requests.length, 1);
});

test("a restored global page that lost access silently opens the default", async (t) => {
  const client = preferenceClient({ views: {}, last_location: "/actors?project=all" });
  const baseCall = client.call.bind(client);
  client.call = async (request) => request.function === "actors.roster"
    ? { status: 403, envelope: { success: false, error: { code: "permission_denied" } } }
    : baseCall(request);
  const mounted = await mountAt(t, "", client);
  assert.equal(mounted.windowNode.location.href, "/strategy?project=all");
  assert.doesNotMatch(mounted.root.textContent, /read failed/);
});

test("list-backed details require an exact row; malformed and unsupported routes are refused", async () => {
  const client = { async call() { return ok({ rows: [{ id: "other" }] }); } };
  assert.equal(await locationResolves(client, "/deployments/runs/missing?project=1", projects), false);
  for (const hash of ["/items/a/extra?project=1", "/items/", "/billing", "https://example.com", "/frontier/unknown"]) {
    assert.equal(await locationResolves(client, hash, projects), false);
  }
  assert.equal(await locationResolves(client, "/billing", projects, { billing: {} }), true);
});

test("resource-backed routes all validate their own result shapes", async () => {
  const routes = [
    ["/strategy/PLAN?project=1", { document: {} }],
    ["/machines/machine", { machine: {} }],
    ["/sessions/session?project=1", { rows: [{ session_id: "session" }] }],
    ["/deployments/flows/flow?project=1", { flows: [{ id: "flow" }] }],
    ["/shipping/run?project=1", { rows: [{ id: "run" }] }],
    ["/qa-methods/command?project=1", { method: {} }],
    ["/qa-plans/1?project=1", { plan: {} }],
    ["/qa-activity/1?project=1", { requirement: {} }],
    ["/ouroboros/1?project=1", { entry: {} }],
    ["/workflows/dash", { workflows: [{ id: "dash" }] }],
    ["/capabilities/test-machine?project=1", { machines: [] }],
  ];
  for (const [hash, result] of routes) {
    assert.equal(await locationResolves({ async call() { return ok(result); } }, hash, projects), true, hash);
    assert.equal(await locationResolves({ async call() { throw new Error("unreachable"); } }, hash, projects), false, hash);
  }
  assert.equal(await locationResolves({}, "/projects/2", projects), true);
  assert.equal(await locationResolves({}, "/projects/gone", projects), false);
});

test("an unavailable preference read preserves the saved value and disables navigation writes", async (t) => {
  const client = preferenceClient({ views: {}, last_location: "/items?project=2" });
  const baseCall = client.call.bind(client);
  client.call = async (request) => request.function === "ui_preferences.screen_selection.list"
    ? { status: 200, envelope: { success: false } } : baseCall(request);
  const mounted = await mountAt(t, "", client);
  await mounted.navigate("/sessions?project=1");
  assert.equal(client.state.last_location, "/items?project=2");
  assert.equal(client.requests.filter((request) => request.payload?.location).length, 0);
});

test("older servers without the response field use the default route", async (t) => {
  const client = preferenceClient({ views: {} });
  const mounted = await mountAt(t, "", client);
  assert.equal(mounted.windowNode.location.href, "/strategy?project=all");
});

test("navigation during a saved-resource read wins over restoration", async () => {
  let finish;
  const windowNode = new FakeDocument().defaultView;
  windowNode.location.href = "/";
  const navigation = createPathNavigation(windowNode);
  const selections = { lastLocation: "/items/example?project=1" };
  const preference = createLocationPreference({
    client: { call() { return new Promise((resolve) => { finish = resolve; }); } },
    windowNode, navigation, selections, isMounted: () => true,
  });
  const restore = preference.restore(projects, {});
  windowNode.location.href = "/inbox";
  finish(ok({ item: {} }));
  await restore;
  assert.equal(windowNode.location.href, "/inbox");
});

test("navigation writes stay serialized and failures only log coded diagnostics", async (t) => {
  const warnings = t.mock.method(console, "warn", () => {});
  const selections = createProjectSelection(null);
  selections.markReady();
  const windowNode = new FakeDocument().defaultView;
  windowNode.location.href = "/items?project=all";
  const navigation = createPathNavigation(windowNode);
  const writes = [];
  let finish;
  const preference = createLocationPreference({
    client: { call(request) {
      writes.push(request.payload.location);
      if (writes.length === 1) return new Promise((resolve) => { finish = resolve; });
      if (writes.length === 2) return Promise.resolve({
        status: 400, envelope: { success: false, error: { code: "payload_invalid" } },
      });
      if (writes.length === 3) throw new Error("connection lost");
      return Promise.resolve(ok({}));
    } }, windowNode, navigation, selections, isMounted: () => true,
  });
  preference.remember();
  preference.remember();
  await settle();
  windowNode.location.href = "/sessions?project=all";
  preference.remember();
  await settle();
  assert.deepEqual(writes, ["/items?project=all"]);
  finish(ok({}));
  await settle();
  assert.deepEqual(writes, ["/items?project=all", "/sessions?project=all"]);
  assert.equal(selections.notice, "");
  assert.deepEqual(warnings.mock.calls[0].arguments, [
    "Last page save failed", { code: "payload_invalid", status: 400 },
  ]);
  windowNode.location.href = "/inbox?project=all";
  preference.remember();
  await settle();
  assert.equal(selections.notice, "");
  assert.deepEqual(warnings.mock.calls[1].arguments, [
    "Last page save failed", {
      code: "location_save_network_failed", message: "Error: connection lost",
    },
  ]);
  windowNode.location.href = "/strategy?project=all";
  preference.remember();
  await settle();
  assert.equal(writes.at(-1), "/strategy?project=all");
  assert.equal(warnings.mock.calls.length, 2);
});

test("a failed last-page save leaves the mounted header clean", async (t) => {
  const warnings = t.mock.method(console, "warn", () => {});
  const client = preferenceClient();
  const baseCall = client.call.bind(client);
  client.call = async (request) => request.payload?.location
    ? { status: 400, envelope: { success: false, error: { code: "payload_invalid" } } }
    : baseCall(request);
  const mounted = await mountAt(t, "/orgs/acme/strategy", client, "/orgs/acme");
  for (const view of ["items", "sessions", "strategy"]) {
    await mounted.navigate(`/orgs/acme/${view}?project=1`);
    assert.doesNotMatch(byClass(mounted.root, "topbar")[0].textContent, /Last page|payload_invalid|Reload to retry/);
  }
  const saves = warnings.mock.calls.filter(call => call.arguments[0] === "Last page save failed");
  assert.ok(saves.length >= 3);
  assert.ok(saves.every((call) => call.arguments[1].code === "payload_invalid"));
});

test("hosted navigation saves path-only locations and restores them on a bare visit", async (t) => {
  const client = preferenceClient();
  const mounted = await mountAt(t, "/orgs/acme/strategy", client, "/orgs/acme");
  for (const view of ["items", "sessions", "strategy"]) {
    await mounted.navigate(`/orgs/acme/${view}?project=1`);
    assert.equal(client.state.last_location, `/${view}?project=1`);
  }
  const writes = client.requests.filter((request) => request.payload?.location);
  assert.ok(writes.every((request) => request.payload.location.startsWith("/") &&
    !request.payload.location.includes("#") && !request.payload.location.includes("/orgs/")));
  mounted.app.unmount();
  const restored = await mountAt(t, "/orgs/acme", preferenceClient(client.state), "/orgs/acme");
  assert.equal(restored.windowNode.location.href, "/orgs/acme/strategy?project=1");
});

test("hosted bare entry retains restored access-loss fallback after remembering", async (t) => {
  const client = preferenceClient({ views: {}, last_location: "/actors?project=all" });
  const baseCall = client.call.bind(client);
  client.call = async (request) => request.function === "actors.roster"
    ? { status: 403, envelope: { success: false, error: { code: "permission_denied" } } }
    : baseCall(request);
  const mounted = await mountAt(t, "/orgs/acme", client, "/orgs/acme");
  assert.equal(mounted.windowNode.location.href, "/orgs/acme/strategy?project=all");
  assert.equal(client.state.last_location, "/strategy?project=all");
  assert.doesNotMatch(mounted.root.textContent, /permission_denied/);
});
