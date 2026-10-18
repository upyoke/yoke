import assert from "node:assert/strict";
import test from "node:test";
import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { loadDelivery } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_shipping_runs.js";
import { prefetchShippingOverview } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_shipping_prefetch.js";
import { VIEW_RENDERERS } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views.js";
import { FakeDocument, byClass, response, settle } from "./universe_ui_dom_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });
const deferred = () => {
  let resolve;
  const promise = new Promise((finish) => { resolve = finish; });
  return { promise, resolve };
};
const projects = [1, 2].map((id) => ({ id, slug: `project-${id}`, name: `Project ${id}` }));
const run = (project) => ({
  id: `release-${project}`, project: `project-${project}`, project_id: project,
  status: "executing", flow: "release", target_environment: "prod",
  created_at: "2026-01-01T00:00:00Z", member_items: [], gates: [],
});

function mountedShipping(t, client) {
  const documentNode = new FakeDocument();
  const windowNode = documentNode.defaultView;
  windowNode.location.href = "/orgs/example/shipping";
  windowNode.fetch = () => response(503, {});
  const root = documentNode.createElement("div");
  const app = mountUniverseApp(root, { client, basePath: "/orgs/example" });
  t.after(() => app.unmount());
  return { root, app, windowNode };
}

test("Shipping starts during bootstrap and paints once using saved scope", async (t) => {
  const preload = t.mock.method(VIEW_RENDERERS.shipping, "preload");
  const roster = deferred(), preferences = deferred(), overview = deferred();
  const calls = [];
  const client = { call(request) {
    calls.push(request);
    if (request.function === "projects.list") return roster.promise;
    if (request.function === "ui_preferences.screen_selection.list") return preferences.promise;
    if (request.function === "deployment_runs.list") return overview.promise;
    return Promise.resolve(ok({ rows: [], flows: [], needs_decision: [] }));
  } };
  const { root, app, windowNode } = mountedShipping(t, client);
  await settle();
  assert.equal(preload.mock.callCount(), 1);
  assert.equal(calls.filter((call) => call.function === "deployment_runs.list").length, 1);
  assert.deepEqual(calls.find((call) => call.function === "deployment_runs.list").payload,
    { relevance: "overview" });
  overview.resolve(ok({ rows: [run(1), run(2)] }));
  await settle();
  assert.equal(byClass(root, "shipping-run-card").length, 0);
  roster.resolve(ok({ rows: projects }));
  preferences.resolve(ok({ views: { shipping: { selection: ["2"], focus: null } } }));
  await settle();
  const cards = byClass(root, "shipping-run-card");
  assert.equal(cards.length, 1);
  assert.match(cards[0].textContent, /release-2/);
  assert.doesNotMatch(cards[0].textContent, /release-1/);
  assert.equal(calls.filter((call) => call.function === "deployment_runs.list").length, 1);
  app.unmount();
  assert.equal(windowNode.listenerCounts.get("popstate"), 0);
});

test("an overview failure still shows its refusal after bootstrap", async (t) => {
  const client = { async call(request) {
    if (request.function === "projects.list") return ok({ rows: projects });
    if (request.function === "deployment_runs.list") throw new Error("overview unavailable");
    return ok({ rows: [], flows: [] });
  } };
  const { root } = mountedShipping(t, client);
  await settle();
  assert.match(root.textContent, /overview unavailable/);
  assert.equal(byClass(root, "shipping-run-card").length, 0);
});

test("navigation discards the early read and later renders read fresh facts", async () => {
  const documentNode = new FakeDocument(), initial = deferred();
  let count = 0;
  const context = {
    document: documentNode, isMounted: () => true, projects: () => [],
    client: { call(request) {
      assert.equal(request.function, "deployment_runs.list");
      count += 1;
      return count === 1 ? initial.promise : Promise.resolve(ok({ rows: [run(count)] }));
    } },
  };
  const windowNode = documentNode.defaultView;
  const dispose = prefetchShippingOverview(context, windowNode, {
    current: () => "/orgs/example/shipping", basePath: "/orgs/example",
  });
  windowNode.dispatchEvent(new Event("popstate"));
  const host = documentNode.createElement("div");
  await loadDelivery(context, host, () => "all");
  assert.equal(count, 2);
  assert.match(host.textContent, /release-2/);
  initial.resolve(ok({ rows: [run(1)] }));
  await settle();
  assert.doesNotMatch(host.textContent, /release-1/);
  await loadDelivery(context, host, () => "all");
  assert.equal(count, 3);
  assert.match(host.textContent, /release-3/);
  dispose();
  assert.equal(windowNode.listenerCounts.get("popstate"), 0);
});

test("other entries and Shipping details do not start overview reads", () => {
  const windowNode = new FakeDocument().defaultView;
  for (const href of ["/strategy", "/shipping/release-1?project=1", "/"]) {
    const context = { client: { call() { assert.fail("unexpected overview"); } } };
    prefetchShippingOverview(context, windowNode, { current: () => href })();
    assert.equal(context.takeShippingOverview, undefined);
  }
});
