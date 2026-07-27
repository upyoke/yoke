import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument, byClass, response, settle,
} from "./universe_ui_dom_test_support.mjs";

function keyEvent(key, extras = {}) {
  const event = new Event("keydown");
  Object.defineProperties(event, {
    key: { value: key },
    metaKey: { value: Boolean(extras.metaKey) },
    ctrlKey: { value: Boolean(extras.ctrlKey) },
  });
  return event;
}

test("shared shell search, footer, identity, and scroll contract are live", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const client = {
    async call(request) {
      if (request.function === "projects.list") {
        return { status: 200, envelope: { success: true, result: {
          rows: [{ id: 1, slug: "yoke", name: "Yoke" }],
        } } };
      }
      if (request.function === "items.overview.list") {
        return { status: 200, envelope: { success: true, result: {
          rows: [{
            id: 21, public_ref: "YOK-21", title: "Build shell",
            project_id: 1, project: "yoke", status: "implementing",
          }],
        } } };
      }
      if (request.function === "sessions.list") {
        return { status: 200, envelope: { success: true, result: {
          rows: [{
            session_id: "session-shell", project_id: 1, project: "yoke",
            current_item: "YOK-21", current_item_title: "Build shell",
            executor: "codex",
          }],
        } } };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const mounted = mountUniverseApp(root, {
    client,
    currentActor: { id: 2, kind: "human", label: "ben" },
    environmentLabel: "stage · yoke",
    versionLabel: "v9.4.1",
  });
  await settle();

  assert.equal(byClass(root, "header-search-input").length, 1);
  assert.equal(byClass(root, "actor-avatar")[0].textContent, "b");
  assert.equal(byClass(root, "actor-kind")[0].textContent, "actor 2");
  assert.equal(byClass(root, "app-footer-environment")[0].textContent,
    "stage · yoke");
  assert.equal(byClass(root, "app-footer-version")[0].textContent, "v9.4.1");
  assert.match(byClass(root, "app-footer-link")[0].href,
    /github\.com\/upyoke\/yoke\/tree\/main\/docs/);

  const input = byClass(root, "header-search-input")[0];
  input.value = "shell";
  input.dispatchEvent(new Event("input"));
  await settle();
  const links = byClass(root, "header-search-result");
  assert.equal(links.length, 2);
  assert.equal(links[0].href, "#/items/YOK-21?project=1");
  assert.equal(links[1].href, "#/sessions?project=1");

  input.dispatchEvent(keyEvent("ArrowDown"));
  input.dispatchEvent(keyEvent("Enter"));
  assert.equal(documentNode.defaultView.location.hash,
    "#/items/YOK-21?project=1");
  const main = byClass(root, "content")[0];
  main.scrollTop = 600;
  documentNode.defaultView.location.hash = "#/sessions?project=1";
  documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  assert.equal(main.scrollTop, 0);

  const keyboard = byClass(root, "keyboard-help-toggle")[0];
  keyboard.dispatchEvent(new Event("click"));
  assert.equal(byClass(root, "keyboard-help")[0].hidden, false);
  documentNode.defaultView.dispatchEvent(keyEvent("Escape"));
  assert.equal(byClass(root, "keyboard-help")[0].hidden, true);
  mounted.unmount();
  assert.equal(documentNode.defaultView.listenerCounts.get("keydown"), 0);
});

test("compact route changes reveal the active destination without moving the desktop rail", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  let navDirection = "column";
  const scrollCalls = [];
  const createElement = documentNode.createElement.bind(documentNode);
  documentNode.createElement = (tagName) => {
    const node = createElement(tagName);
    node.scrollIntoView = (options) => {
      scrollCalls.push({ node, options });
    };
    return node;
  };
  documentNode.defaultView.getComputedStyle = (node) => ({
    flexDirection: node.classList.contains("sidenav")
      ? navDirection : "column",
  });
  const root = documentNode.createElement("div");
  const client = {
    async call(request) {
      if (request.function === "projects.list") {
        return { status: 200, envelope: { success: true, result: {
          rows: [{ id: 1, slug: "yoke", name: "Yoke" }],
        } } };
      }
      if (request.function === "items.overview.list") {
        return { status: 200, envelope: { success: true, result: {
          rows: [],
        } } };
      }
      if (request.function === "sessions.list") {
        return { status: 200, envelope: { success: true, result: {
          rows: [],
        } } };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const mounted = mountUniverseApp(root, { client });
  await settle();

  assert.equal(scrollCalls.length, 0);
  navDirection = "row";
  documentNode.defaultView.location.hash = "#/sessions?project=1";
  documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  await settle();

  assert.equal(
    scrollCalls.at(-1).node.children[1].textContent,
    "Sessions",
  );
  assert.deepEqual(
    scrollCalls.at(-1).options,
    { block: "nearest", inline: "nearest" },
  );
  const compactScrollCount = scrollCalls.length;
  navDirection = "column";
  documentNode.defaultView.location.hash = "#/items?project=1";
  documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  await settle();
  assert.equal(scrollCalls.length, compactScrollCount);

  mounted.unmount();
});
