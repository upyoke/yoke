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

async function mountDrawer(t, initiallyNarrow = true) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  let narrow = initiallyNarrow;
  documentNode.defaultView.getComputedStyle = (node) => ({
    display: node.classList.contains("navigation-toggle") && !narrow ? "none" : "block",
  });
  documentNode.defaultView.location.href = "/strategy";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client: injectedClient("drawer") });
  await settle();
  const resize = (next) => {
    narrow = next;
    documentNode.defaultView.dispatchEvent(new Event("resize"));
  };
  return { documentNode, root, mounted, resize };
}

test("an open drawer makes the page behind it inert", async (t) => {
  const { documentNode, root, mounted } = await mountDrawer(t);
  const toggle = byClass(root, "navigation-toggle")[0];
  const body = byClass(root, "workbench-body")[0];
  const firstControl = byClass(root, "onboarding-open")[0] || byClass(root, "nav-link")[0];

  assert.equal(body.inert, false);
  assert.equal(byClass(root, "navigation-close").length, 0);
  assert.equal(toggle.getAttribute("aria-expanded"), "false");

  toggle.dispatchEvent(new Event("click"));
  assert.equal(body.inert, true);
  assert.equal(documentNode.activeElement, firstControl);
  assert.equal(byClass(root, "navigation-scrim")[0].hidden, false);
  assert.equal(toggle.getAttribute("aria-expanded"), "true");
  assert.equal(toggle.getAttribute("aria-label"), "Close navigation");
  mounted.unmount();
});

test("dismissing the drawer returns focus to the control that opened it", async (t) => {
  const { documentNode, root, mounted } = await mountDrawer(t);
  const toggle = byClass(root, "navigation-toggle")[0];

  for (const dismissal of [
    () => toggle.dispatchEvent(new Event("click")),
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

test("following a destination closes the drawer and focuses the new page", async (t) => {
  const { documentNode, root, mounted } = await mountDrawer(t);
  const toggle = byClass(root, "navigation-toggle")[0];
  toggle.dispatchEvent(new Event("click"));
  const link = byClass(root, "nav-link")[1];
  documentNode.activeElement = link;
  link.dispatchEvent(new Event("click"));
  // The selected link becomes inert with the closed drawer. Focus belongs
  // to the page, not to an invisible destination or the old toggle.
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(byClass(root, "workbench-body")[0].inert, false);
  assert.equal(documentNode.activeElement, byClass(root, "content")[0]);
  mounted.unmount();
});

test("a closed narrow drawer is inert but wide navigation remains available", async (t) => {
  const { root, mounted, resize } = await mountDrawer(t);
  const navigation = byClass(root, "sidenav")[0];
  assert.equal(navigation.inert, true);
  resize(false);
  assert.equal(navigation.inert, false);
  resize(true);
  assert.equal(navigation.inert, true);
  mounted.unmount();
});

test("widening an open drawer clears every background restriction", async (t) => {
  const { documentNode, root, mounted, resize } = await mountDrawer(t);
  const toggle = byClass(root, "navigation-toggle")[0];
  const background = ["topbar", "workbench-body", "app-footer"]
    .map((name) => byClass(root, name)[0]);
  toggle.dispatchEvent(new Event("click"));
  assert.ok(background.every((node) => node.inert));
  assert.equal(documentNode.activeElement, byClass(root, "onboarding-open")[0] || byClass(root, "nav-link")[0]);
  resize(false);
  assert.ok(background.every((node) => !node.inert));
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(byClass(root, "navigation-scrim")[0].hidden, true);
  assert.equal(byClass(root, "sidenav")[0].inert, false);
  assert.equal(documentNode.activeElement, byClass(root, "onboarding-open")[0] || byClass(root, "nav-link")[0]);
  resize(true);
  assert.equal(byClass(root, "sidenav")[0].inert, true);
  mounted.unmount();
  assert.equal(documentNode.defaultView.listenerCounts.get("resize"), 0);
});

test("drawer tab order stays visible and skips collapsed destinations", async (t) => {
  const { documentNode, root, mounted } = await mountDrawer(t);
  byClass(root, "navigation-toggle")[0].dispatchEvent(new Event("click"));
  const firstControl = byClass(root, "onboarding-open")[0] || byClass(root, "nav-link")[0];
  const diagnostics = byClass(root, "nav-group").find((node) => node.textContent === "Diagnostics");
  const tab = (shiftKey = false) => {
    const event = new Event("keydown");
    event.key = "Tab";
    event.shiftKey = shiftKey;
    documentNode.defaultView.dispatchEvent(event);
  };
  assert.equal(documentNode.activeElement, firstControl);
  tab(true);
  assert.equal(documentNode.activeElement, diagnostics);
  tab();
  assert.equal(documentNode.activeElement, firstControl);
  diagnostics.dispatchEvent(new Event("click"));
  const lastLink = byClass(root, "nav-link").at(-1);
  documentNode.activeElement = lastLink;
  tab();
  assert.equal(documentNode.activeElement, firstControl);
  mounted.unmount();
});

test("sidebar inset follows a wrapping header and releases its observer", async (t) => {
  const { documentNode, root, mounted } = await mountDrawer(t, false);
  const header = byClass(root, "topbar")[0];
  const shell = byClass(root, "shell")[0];
  header.getBoundingClientRect = () => ({ height: 96 });
  documentNode.defaultView.dispatchEvent(new Event("resize"));
  assert.equal(shell.style.getPropertyValue("--yoke-app-header-height"), "96px");
  mounted.unmount();
  assert.equal(shell.style.getPropertyValue("--yoke-app-header-height"), "");
});
