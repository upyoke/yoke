import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  resetOverviewDisclosureState,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_overview_primitives.js";
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
  t.after(() => {
    globalThis.fetch = originalFetch;
    resetOverviewDisclosureState();
  });
  globalThis.fetch = () => response(200, {});
  resetOverviewDisclosureState();
}

async function mountOverview(documentNode) {
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client: overviewClient() });
  await settle();
  return { mounted, root };
}

test("Overview anatomy is native disclosures, document cards, and five named bands", async (t) => {
  stubFetch(t);
  const { mounted, root } = await mountOverview(new FakeDocument());
  const sections = byClass(root, "overview-section");
  assert.equal(sections.length, 2);
  assert.equal(sections.every((node) => node.tagName === "DETAILS"), true);
  assert.equal(sections.every((node) => node.children[0].tagName === "SUMMARY"), true);
  assert.deepEqual(
    byClass(root, "overview-section-title").map((node) => node.textContent),
    ["Strategy", "Frontier"],
  );

  const bands = byClass(root, "overview-band");
  assert.equal(bands.every((node) => node.tagName === "DETAILS"), true);
  assert.deepEqual(
    byClass(root, "overview-band-title").map((node) => node.textContent),
    ["Standing", "Plans", "Waiting", "Ready", "Active", "Shipping", "Done (24h)"],
  );
  assert.deepEqual(
    bands.slice(2).map((node) => node.attributes.get("data-fold")),
    ["band:waiting", "band:ready", "band:active", "band:shipping", "band:done"],
  );

  const docs = byClass(root, "overview-doc-card");
  assert.equal(docs.length, 2);
  assert.equal(byClass(root, "overview-doc-age-dot").length, 2);
  assert.deepEqual(
    byClass(root, "overview-doc-claim-label").map((node) => node.textContent),
    ["Steering", "Blitz"],
  );
  assert.deepEqual(
    byClass(root, "overview-doc-state").map((node) => node.textContent),
    ["locked"],
  );
  assert.deepEqual(
    byClass(root, "overview-doc-summary").map((node) => node.textContent),
    ["Build a calmer delivery system.", "Ship the next reliable slice."],
  );
  const leafText = allNodes(root)
    .filter((node) => node.children.length === 0)
    .map((node) => node.textContent);
  assert.equal(leafText.filter(
    (text) => text === "Build a calmer delivery system.",
  ).length, 1, "authored summary renders exactly once");

  const session = byClass(root, "session-card")[0];
  assert.equal(session.attributes.get("data-session-id"), "s-run");
  assert.equal(byClass(session, "session-model-line").length, 1);
  assert.equal(byClass(root, "overview-run-batch").length, 1);
  assert.equal(byClass(root, "delivery-stage-bar").length, 1);
  mounted.unmount();
});

test("a closed disclosure remains closed across a complete rerender", async (t) => {
  stubFetch(t);
  const documentNode = new FakeDocument();
  const first = await mountOverview(documentNode);
  const frontier = byClass(first.root, "overview-section")[1];
  frontier.open = false;
  frontier.dispatchEvent(new Event("toggle"));
  first.mounted.unmount();

  const second = await mountOverview(documentNode);
  assert.equal(byClass(second.root, "overview-section")[1].open, false);
  second.mounted.unmount();
});
