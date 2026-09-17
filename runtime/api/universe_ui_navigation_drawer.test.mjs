// At narrow width the sidebar is a drawer over the page: it owns the screen
// while it is open, and dismissing it leaves the reader where they were.

import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  byClass,
  injectedClient,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

async function mountDrawer(t) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/strategy";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client: injectedClient("drawer") });
  await settle();
  return { documentNode, root, mounted };
}

test("an open drawer makes the page behind it inert", async (t) => {
  const { root, mounted } = await mountDrawer(t);
  const toggle = byClass(root, "navigation-toggle")[0];
  const body = byClass(root, "workbench-body")[0];
  const close = byClass(root, "navigation-close")[0];

  assert.equal(body.inert, false);
  assert.equal(close.hidden, true);
  assert.equal(toggle.getAttribute("aria-expanded"), "false");

  toggle.dispatchEvent(new Event("click"));
  assert.equal(body.inert, true);
  assert.equal(close.hidden, false);
  assert.equal(byClass(root, "navigation-scrim")[0].hidden, false);
  assert.equal(toggle.getAttribute("aria-expanded"), "true");
  assert.equal(toggle.getAttribute("aria-label"), "Close navigation");
  mounted.unmount();
});

test("dismissing the drawer returns focus to the control that opened it", async (t) => {
  const { documentNode, root, mounted } = await mountDrawer(t);
  const toggle = byClass(root, "navigation-toggle")[0];
  const close = byClass(root, "navigation-close")[0];

  for (const dismissal of [
    () => close.dispatchEvent(new Event("click")),
    () => byClass(root, "navigation-scrim")[0].dispatchEvent(new Event("click")),
    () => {
      const event = new Event("keydown");
      event.key = "Escape";
      documentNode.defaultView.dispatchEvent(event);
    },
  ]) {
    toggle.dispatchEvent(new Event("click"));
    documentNode.activeElement = byClass(root, "nav-link")[0];
    dismissal();
    assert.equal(documentNode.activeElement, toggle);
    assert.equal(byClass(root, "workbench-body")[0].inert, false);
  }
  mounted.unmount();
});

test("a closed drawer is left alone, so Escape never steals focus", async (t) => {
  const { documentNode, root, mounted } = await mountDrawer(t);
  const elsewhere = byClass(root, "nav-link")[0];
  documentNode.activeElement = elsewhere;
  const event = new Event("keydown");
  event.key = "Escape";
  documentNode.defaultView.dispatchEvent(event);
  // Escape is a document-wide gesture other surfaces answer too; a drawer
  // that was not open has no focus to hand back.
  assert.equal(documentNode.activeElement, elsewhere);
  mounted.unmount();
});

test("following a destination closes the drawer without taking focus back", async (t) => {
  const { documentNode, root, mounted } = await mountDrawer(t);
  const toggle = byClass(root, "navigation-toggle")[0];
  toggle.dispatchEvent(new Event("click"));
  const link = byClass(root, "nav-link")[1];
  documentNode.activeElement = link;
  link.dispatchEvent(new Event("click"));
  // The drawer is gone, and focus stays with the navigation that happened.
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(byClass(root, "workbench-body")[0].inert, false);
  assert.equal(documentNode.activeElement, link);
  mounted.unmount();
});
