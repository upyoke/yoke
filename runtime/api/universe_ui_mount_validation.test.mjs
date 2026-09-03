import assert from "node:assert/strict";
import test from "node:test";

import {
  UNIVERSE_APP_CONTRACT_VERSION,
  buildUniverseRoute,
  mountUniverseApp,
  parseUniverseRoute,
  universeNavScope,
} from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  FakeNode,
  allNodes,
  byClass,
  cellText,
  injectedClient,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

test("mount rejects non-elements and rolls back throwing slot factories", () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const retained = documentNode.createElement("aside");
  const fragment = new FakeNode(documentNode, "fragment", 11);
  const client = injectedClient("unused");

  assert.throws(() => mountUniverseApp(root, {
    client,
    slots: { topbarStart: retained, topbarEnd: fragment },
  }), /slot content must be an Element/);
  assert.equal(retained.parentNode, null);
  assert.equal(root.children.length, 0);
  assert.ok(!root.classList.contains("universe-app-root"));

  assert.throws(() => mountUniverseApp(root, {
    client,
    slots: {
      topbarStart: retained,
      topbarEnd: () => { throw new Error("slot factory failed"); },
    },
  }), /slot factory failed/);
  assert.equal(retained.parentNode, null);
  assert.equal(root.children.length, 0);
  assert.equal(client.requests.length, 0);

  const host = documentNode.createElement("section");
  host.appendChild(root);
  assert.throws(() => mountUniverseApp(root, {
    client, slots: { topbarStart: host },
  }), /mount root or its ancestor/);
  assert.equal(root.parentNode, host);
  assert.equal(host.children[0], root);
  assert.throws(() => mountUniverseApp(root, {
    client, slots: { topbarStart: root },
  }), /mount root or its ancestor/);

  const svgRoot = documentNode.createElement("svg");
  svgRoot.namespaceURI = "http://www.w3.org/2000/svg";
  assert.throws(() => mountUniverseApp(svgRoot, { client }),
    /requires an HTML element root/);
});

test("mount rejects section content the way it rejects slot content", () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const node = documentNode.createElement("section");
  const fragment = new FakeNode(documentNode, "fragment", 11);
  const client = injectedClient("unused");

  assert.throws(() => mountUniverseApp(root, {
    client, sections: { members: fragment },
  }), /section content must be an Element/);
  assert.throws(() => mountUniverseApp(root, {
    client, sections: { members: node, billing: node },
  }), /cannot occupy two universe app slots or sections/);
  // The duplicate ledger spans slots and sections: one Element cannot stand
  // in a slot and a section at once.
  assert.throws(() => mountUniverseApp(root, {
    client, slots: { contentAfter: node }, sections: { members: node },
  }), /cannot occupy two universe app slots or sections/);
  // A placement the contract does not define is refused by name rather than
  // silently falling back to the default.
  assert.throws(() => mountUniverseApp(root, {
    client, sections: { members: { content: node, placement: "sideways" } },
  }), /placement must be one of inView, beforeScope/);
  assert.equal(root.children.length, 0);
  assert.equal(node.parentNode, null);
  assert.equal(client.requests.length, 0);
});

test("a synchronously throwing client still returns a cleanup handle", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const slot = documentNode.createElement("aside");
  const client = { call() { throw new Error("synchronous client failure"); } };

  const mounted = mountUniverseApp(root, {
    client, slots: { topbarStart: slot },
  });
  assert.equal(typeof mounted.unmount, "function");
  await settle();
  assert.ok(root.classList.contains("universe-app-root"));
  mounted.unmount();
  assert.equal(root.children.length, 0);
  assert.equal(slot.parentNode, null);
  assert.ok(!root.classList.contains("universe-app-root"));
});

test("route helpers are deterministic and platform-neutral", () => {
  assert.deepEqual(parseUniverseRoute("#/strategy?project=abc%201"), {
    view: "strategy", tab: null, detail: null, project: "abc 1",
  });
  // An unrecognised view falls back to the first destination in the nav.
  assert.deepEqual(parseUniverseRoute("#/unknown"), {
    view: "overview", tab: null, detail: null, project: null,
  });
  // Board rendering remains a CLI/local artifact; it is not a web route.
  assert.deepEqual(parseUniverseRoute("#/board"), {
    view: "overview", tab: null, detail: null, project: null,
  });
  assert.equal(buildUniverseRoute("strategy", "abc 1"),
    "#/strategy?project=abc%201");
  assert.equal(buildUniverseRoute("unknown", null), "#/overview");
  assert.equal(buildUniverseRoute("board", null), "#/overview");
});

test("every nav destination declares how it takes project scope", () => {
  for (const view of ["items", "strategy", "overview", "inbox", "sessions"]) {
    assert.equal(universeNavScope(view), "multi");
  }
  // Project settings is a drill-in on Projects, not a destination, so GitHub
  // is the only single-project one left.
  for (const view of ["github"]) {
    assert.equal(universeNavScope(view), "single");
  }
  // Workflows serves the engine's universe-wide lifecycle definition, so no
  // project narrows it and it draws no picker.
  for (const view of [
    "projects", "access", "packs", "organization", "workflows",
  ]) {
    assert.equal(universeNavScope(view), "none");
  }
  // Members and Billing are host-fed views: the workbench routes them like
  // any destination, and no project narrows a host-owned screen.
  for (const hostFed of ["members", "billing"]) {
    assert.equal(universeNavScope(hostFed), "none");
    assert.deepEqual(parseUniverseRoute(`#/${hostFed}`), {
      view: hostFed, tab: null, detail: null, project: null,
    });
  }
});
