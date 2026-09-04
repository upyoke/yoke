import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import { multiProjectOverviewClient } from "./universe_ui_overview_view_test_support.mjs";

const sessionIds = (root) => byClass(root, "session-card")
  .map((node) => node.attributes.get("data-session-id"));
const runIds = (root) => byClass(root, "overview-run-id")
  .map((node) => node.textContent);
const docSlugs = (root) => byClass(root, "overview-doc-slug")
  .map((node) => node.textContent);
const callCount = (client, functionId) => client.requests.filter(
  (request) => request.function === functionId,
).length;

function stubFetch(t) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
}

async function navigate(windowNode, hash) {
  windowNode.location.hash = hash;
  windowNode.dispatchEvent(new Event("hashchange"));
  await settle();
}

test("a project change repaints Overview from held data with zero reads", async (t) => {
  stubFetch(t);
  const documentNode = new FakeDocument();
  const windowNode = documentNode.defaultView;
  windowNode.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");
  const client = multiProjectOverviewClient();
  const mounted = mountUniverseApp(root, { client });
  await settle();

  const before = client.requests.length;
  assert.equal(callCount(client, "overview.activation.get"), 1);
  assert.equal(callCount(client, "strategy.doc.list"), 2);
  assert.equal(callCount(client, "strategy.doc_claim.list"), 2);
  assert.equal(callCount(client, "deployment_runs.list"), 2);
  assert.deepEqual(sessionIds(root), ["s-yoke"]);
  assert.deepEqual(runIds(root), ["run-yoke"]);
  assert.deepEqual(docSlugs(root), ["MISSION"]);

  const activationHost = byClass(root, "activation-host")[0];
  const scopeBar = byClass(root, "scope-bar")[0];
  const pageHead = byClass(root, "page-head")[0];
  const strategySection = byClass(root, "overview-section")[0];

  await navigate(windowNode, "#/overview?project=2");
  assert.equal(client.requests.length, before);
  assert.deepEqual(sessionIds(root), ["s-beta"]);
  assert.deepEqual(runIds(root), ["run-beta"]);
  assert.deepEqual(docSlugs(root), ["BETA-PLAN"]);
  assert.equal(byClass(root, "activation-host")[0], activationHost);
  assert.equal(byClass(root, "scope-bar")[0], scopeBar);
  assert.equal(byClass(root, "page-head")[0], pageHead);
  assert.equal(byClass(root, "overview-section")[0], strategySection);

  await navigate(windowNode, "#/overview?project=all");
  assert.equal(client.requests.length, before);
  assert.deepEqual(sessionIds(root).sort(), ["s-beta", "s-nil", "s-yoke"]);
  assert.deepEqual(runIds(root).sort(), ["run-beta", "run-yoke"]);
  assert.deepEqual(docSlugs(root).sort(), ["BETA-PLAN", "MISSION"]);
  mounted.unmount();
});

test("prefix chips repaint the held scope in place", async (t) => {
  stubFetch(t);
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");
  const client = multiProjectOverviewClient();
  const mounted = mountUniverseApp(root, { client });
  await settle();
  const before = client.requests.length;
  const chip = (label) => byClass(root, "scope-chip")
    .find((node) => node.textContent === label);
  const chipState = () => byClass(root, "scope-chip").map(
    (node) => [node.textContent, node.classList.contains("on")],
  );

  chip("BET").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(client.requests.length, before);
  assert.deepEqual(sessionIds(root).sort(), ["s-beta", "s-yoke"]);
  assert.deepEqual(chipState(), [["All", false], ["YOK", true], ["BET", true]]);

  chip("YOK").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(client.requests.length, before);
  assert.deepEqual(sessionIds(root), ["s-beta"]);
  assert.equal(documentNode.defaultView.location.hash, "#/overview?project=2");
  mounted.unmount();
});

test("a failed project document read does not poison another scope", async (t) => {
  stubFetch(t);
  const documentNode = new FakeDocument();
  const windowNode = documentNode.defaultView;
  windowNode.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");
  const client = multiProjectOverviewClient({ failProject: "2" });
  const mounted = mountUniverseApp(root, { client });
  await settle();
  const before = client.requests.length;

  assert.equal(byClass(root, "overview-band-error").length, 0);
  await navigate(windowNode, "#/overview?project=2");
  assert.equal(client.requests.length, before);
  assert.equal(byClass(root, "overview-band-error").length, 2);
  await navigate(windowNode, "#/overview?project=1");
  assert.equal(client.requests.length, before);
  assert.equal(byClass(root, "overview-band-error").length, 0);
  mounted.unmount();
});
