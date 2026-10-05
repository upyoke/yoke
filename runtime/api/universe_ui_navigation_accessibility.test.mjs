import assert from "node:assert/strict";
import test from "node:test";

import { createScopePicker } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_navigation.js";
import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { historyReviewView } from "../../packages/yoke-core/src/yoke_core/ui/static/strategy_view_primitives.js";
import { FakeDocument, allNodes, byClass, injectedClient, response, settle } from "./universe_ui_dom_test_support.mjs";

test("scope buttons expose selected state through every toggle and external rescope", () => {
  const documentNode = new FakeDocument();
  const bar = createScopePicker({
    documentNode, entry: { scope: "multi" }, scope: "all",
    projects: [{ id: 1 }, { id: 2 }, { id: 3 }], onSelect() {},
  });
  const chips = byClass(bar, "scope-chip");
  const selected = () => chips.map((chip) => chip.getAttribute("aria-pressed"));
  assert.equal(bar.getAttribute("role"), "group");
  assert.deepEqual(selected(), ["true", "false", "false", "false"]);
  chips[1].dispatchEvent(new Event("click"));
  assert.deepEqual(selected(), ["false", "true", "false", "false"]);
  chips[2].dispatchEvent(new Event("click"));
  assert.deepEqual(selected(), ["false", "true", "true", "false"]);
  bar.setScope(["3"]);
  assert.deepEqual(selected(), ["false", "false", "false", "true"]);
});

test("Items leads Diagnostics and the active route is announced", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = "/items";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client: injectedClient("nav") });
  t.after(() => mounted.unmount());
  await settle();
  const links = byClass(root, "nav-link");
  const items = links.find((node) => node.textContent === "Items");
  assert.equal(items.parentNode.id, "universe-nav-group-items-diagnostics");
  assert.ok(byClass(items.parentNode, "nav-link")[0] === items, "Items is first in Diagnostics");
  assert.equal(items.getAttribute("aria-current"), "page");
  documentNode.defaultView.location.href = "/strategy";
  documentNode.defaultView.dispatchEvent(new Event("popstate"));
  await settle();
  assert.equal(items.getAttribute("aria-current"), null);
  assert.equal(links.find((node) => node.textContent === "Strategy").getAttribute("aria-current"), "page");
});

test("strategy revision selectors have distinct associated labels", () => {
  const documentNode = new FakeDocument();
  const view = historyReviewView({ document: documentNode }, "demo", {
    revisions: [], slug: "DIRECTION",
  }, () => {});
  const labels = allNodes(view).filter((node) => node.tagName === "LABEL");
  const selects = byClass(view, "strategy-revision-select");
  for (const [index, label] of ["From", "To"].entries()) {
    assert.equal(labels.find((node) => node.textContent === label).getAttribute("for"), selects[index].id);
  }
  assert.notEqual(selects[0].id, selects[1].id);
});
