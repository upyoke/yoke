import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import { overviewClient } from "./universe_ui_overview_view_test_support.mjs";

function stubFetch(t) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
}

test("Overview asks Strategy and Frontier without duplicate page chrome", async (t) => {
  stubFetch(t);
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");
  const client = overviewClient();
  const mounted = mountUniverseApp(root, { client });
  await settle();

  assert.deepEqual(
    byClass(root, "overview-section-title").map((node) => node.textContent),
    ["Strategy", "Frontier"],
  );
  assert.equal(byClass(root, "page-head")[0].hidden, true);
  assert.equal(byClass(root, "overview-item-card").length, 3);
  assert.equal(byClass(root, "session-card").length, 1);
  assert.equal(byClass(root, "overview-run-card").length, 1);

  const called = new Set(client.requests.map((request) => request.function));
  for (const functionId of [
    "items.overview.list", "frontier.list", "sessions.list",
    "strategy.doc.list", "strategy.doc_claim.list", "deployment_runs.list",
    "overview.activation.get",
  ]) assert.ok(called.has(functionId), functionId);

  assert.deepEqual(
    byClass(root, "scope-chip").map((node) => node.textContent),
    ["All", "YOK"],
  );
  const contextLabels = byClass(root, "header-context-label")
    .map((node) => node.textContent);
  assert.deepEqual(contextLabels, ["Universe", "Projects", "Actor"]);
  mounted.unmount();
});

test("Overview cards link to their first-class destinations", async (t) => {
  stubFetch(t);
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client: overviewClient() });
  await settle();

  assert.deepEqual(
    byClass(root, "overview-doc-card").map((node) => node.href),
    ["#/strategy/MISSION?project=1", "#/strategy/DELIVERY-PLAN?project=1"],
  );
  assert.deepEqual(
    byClass(root, "overview-item-card").map((node) => node.href),
    ["#/items/7?project=1", "#/items/9?project=1", "#/items/6?project=1"],
  );
  assert.deepEqual(
    byClass(root, "overview-run-card").map((node) => node.href),
    ["#/deployments?project=1"],
  );
  const text = allNodes(root).map((node) => node.textContent || "").join(" ");
  assert.match(text, /Waiting for a product decision/);
  assert.match(text, /No blockers; specification and plan are current/);
  assert.match(text, /Merged and deployed to stage/);
  mounted.unmount();
});
