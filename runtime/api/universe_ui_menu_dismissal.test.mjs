// The shared dismissal contract every transient universe surface attaches:
// a click outside it closes it, Escape closes it and hands focus back to the
// trigger, and going somewhere else closes it too — the gesture a menu whose
// own item is a route link cannot observe for itself.

import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  attachMenuDismissal,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_menu_dismissal.js";
import {
  FakeDocument,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function clickAt(windowNode, target) {
  const event = new Event("click");
  Object.defineProperty(event, "target", { value: target, configurable: true });
  windowNode.dispatchEvent(event);
}

function pressKey(windowNode, key) {
  const event = new Event("keydown");
  Object.defineProperty(event, "key", { value: key, configurable: true });
  windowNode.dispatchEvent(event);
}

function surface() {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const trigger = documentNode.createElement("button");
  const panel = documentNode.createElement("div");
  const outside = documentNode.createElement("div");
  root.appendChild(trigger);
  root.appendChild(panel);
  let open = true;
  const dispose = attachMenuDismissal(documentNode, {
    root,
    close: () => { open = false; },
    isOpen: () => open,
    trigger,
  });
  return {
    documentNode,
    dispose,
    isOpen: () => open,
    outside,
    panel,
    root,
    trigger,
    windowNode: documentNode.defaultView,
  };
}

test("a click outside closes the surface; one inside leaves it open", () => {
  const menu = surface();

  clickAt(menu.windowNode, menu.panel);
  assert.equal(menu.isOpen(), true);
  clickAt(menu.windowNode, menu.trigger);
  assert.equal(menu.isOpen(), true);

  clickAt(menu.windowNode, menu.outside);
  assert.equal(menu.isOpen(), false);
  menu.dispose();
});

test("Escape closes the surface and returns focus to its trigger", () => {
  const menu = surface();

  pressKey(menu.windowNode, "ArrowDown");
  assert.equal(menu.isOpen(), true);

  pressKey(menu.windowNode, "Escape");
  assert.equal(menu.isOpen(), false);
  // Focus has to land somewhere the keyboard can carry on from; dropping it
  // to the document strands the reader at the top of the page.
  assert.equal(menu.documentNode.activeElement, menu.trigger);
  menu.dispose();
});

test("navigating away closes the surface", () => {
  const menu = surface();

  menu.windowNode.dispatchEvent(new Event("hashchange"));
  assert.equal(menu.isOpen(), false);
  menu.dispose();
});

test("a closed surface is left alone, so Escape never steals focus", () => {
  const menu = surface();
  menu.dispose();
  const closed = surface();
  closed.close = null;
  clickAt(closed.windowNode, closed.outside);
  assert.equal(closed.isOpen(), false);

  closed.documentNode.activeElement = null;
  pressKey(closed.windowNode, "Escape");
  assert.equal(closed.documentNode.activeElement, null);
  closed.dispose();
});

test("dispose leaves no listener behind", () => {
  const menu = surface();
  const counts = menu.windowNode.listenerCounts;
  assert.deepEqual(
    ["click", "keydown", "hashchange"].map((type) => counts.get(type)),
    [1, 1, 1],
  );

  menu.dispose();
  assert.deepEqual(
    ["click", "keydown", "hashchange"].map((type) => counts.get(type)),
    [0, 0, 0],
  );
  clickAt(menu.windowNode, menu.outside);
  assert.equal(menu.isOpen(), true);
});

test("a document with no window keeps a working, disposable no-op", () => {
  const documentNode = new FakeDocument();
  documentNode.defaultView = null;
  const root = documentNode.createElement("div");
  const dispose = attachMenuDismissal(documentNode, {
    root,
    close: () => assert.fail("nothing can dismiss without a window"),
    isOpen: () => true,
  });
  assert.equal(typeof dispose, "function");
  dispose();
});

function actorClient() {
  const ok = (result) => ({ status: 200, envelope: { success: true, result } });
  return {
    async call(request) {
      switch (request.function) {
        case "organizations.get":
          return ok({ name: "Local", slug: "local" });
        case "ui_preferences.screen_selection.list":
          return ok({ views: {} });
        case "projects.list":
        case "sessions.list":
          return ok({ rows: [] });
        case "profile.get":
          return ok({
            actor: { id: 2, kind: "human", name: "Ben" },
            identity: { email: "ben@example.test" },
            preferences: {},
          });
        default:
          return ok({});
      }
    },
  };
}

async function mountActorMenu() {
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client: actorClient() });
  await settle();
  await settle();
  const chip = byClass(root, "actor-chip")[0];
  chip.dispatchEvent(new Event("click"));
  return { chip, documentNode, menu: byClass(root, "actor-menu")[0], mounted, root };
}

test("the actor menu closes when its Profile item navigates", async () => {
  const surfaceUnderTest = await mountActorMenu();
  assert.equal(surfaceUnderTest.menu.hidden, false);
  assert.equal(surfaceUnderTest.chip.getAttribute("aria-expanded"), "true");

  // What the reported defect was: the item IS the route link, so the page
  // underneath changed while the panel stayed open over it.
  surfaceUnderTest.documentNode.defaultView.location.hash = "#/profile";
  surfaceUnderTest.documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  assert.equal(surfaceUnderTest.menu.hidden, true);
  assert.equal(surfaceUnderTest.chip.getAttribute("aria-expanded"), "false");
  surfaceUnderTest.mounted.unmount();
});

test("the actor menu closes on Escape and on an outside click", async () => {
  const surfaceUnderTest = await mountActorMenu();
  const windowNode = surfaceUnderTest.documentNode.defaultView;

  pressKey(windowNode, "Escape");
  assert.equal(surfaceUnderTest.menu.hidden, true);
  assert.equal(
    surfaceUnderTest.documentNode.activeElement, surfaceUnderTest.chip,
  );

  surfaceUnderTest.chip.dispatchEvent(new Event("click"));
  assert.equal(surfaceUnderTest.menu.hidden, false);
  clickAt(windowNode, surfaceUnderTest.documentNode.createElement("div"));
  assert.equal(surfaceUnderTest.menu.hidden, true);
  surfaceUnderTest.mounted.unmount();
});

test("unmounting the app takes the actor menu's listeners with it", async () => {
  const surfaceUnderTest = await mountActorMenu();
  const counts = surfaceUnderTest.documentNode.defaultView.listenerCounts;
  const before = counts.get("click");
  assert.ok(before >= 1);

  surfaceUnderTest.mounted.unmount();
  assert.ok(counts.get("click") < before);
});
