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
  injectedClient,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
test("one-argument mount preserves the local client and DOM shape", async (t) => {
  const originalFetch = globalThis.fetch;
  const fetches = [];
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async (input, init) => {
    fetches.push({ url: String(input), init });
    if (!init) return response(200, {});
    const request = JSON.parse(init.body);
    if (request.function === "organizations.get") {
      return response(200, { success: true, result: { name: "Local" } });
    }
    if (request.function === "projects.list") {
      return response(200, {
        success: true, result: { rows: [{ id: 3, name: "Local project" }] },
      });
    }
    return response(200, { success: true, result: { rows: [] } });
  };

  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root);
  await settle();

  assert.equal(mounted.contractVersion, UNIVERSE_APP_CONTRACT_VERSION);
  assert.ok(root.classList.contains("universe-app-root"));
  const [topbar, shellNode] = root.children;
  assert.ok(topbar.classList.contains("topbar"));
  // Shared shell.css owns the prototype's frame height.
  assert.ok(topbar.classList.contains("yoke-app-header"));
  assert.ok(shellNode.classList.contains("shell"));
  // Loopback identity is actor-shaped, never the organization.
  assert.equal(byClass(root, "org-context").length, 0);
  const actor = byClass(root, "actor-chip")[0];
  assert.equal(byClass(actor, "actor-name")[0].textContent, "local actor");
  assert.ok(actor.parentNode.classList.contains("context-side"));
  assert.equal(byClass(root, "capability-actions").length, 0);
  const functionFetches = fetches.filter((entry) => entry.init);
  assert.ok(functionFetches.length >= 2);
  assert.ok(functionFetches.every((entry) => (
    JSON.parse(entry.init.body).function !== "organizations.get"
  )));
  assert.ok(functionFetches.every(
    (entry) => entry.url === "/api/functions/call",
  ));
  const projectRosterRequest = functionFetches
    .map((entry) => JSON.parse(entry.init.body))
    .find((request) => request.function === "projects.list");
  assert.deepEqual(projectRosterRequest.payload, {
    fields: ["id", "slug", "name", "emoji"],
  });
  const assetFetch = fetches.find((entry) => !entry.init);
  assert.match(assetFetch.url, /\/static\/yoke-wordmark\.svg$/);
  assert.doesNotMatch(assetFetch.url, /\/assets\//);
  assert.equal(documentNode.defaultView.listenerCounts.get("hashchange"), 1);
  assert.equal(documentNode.defaultView.listenerCounts.get("keydown"), 1);
  mounted.unmount();
  mounted.unmount();
  assert.equal(root.children.length, 0);
  assert.ok(!root.classList.contains("universe-app-root"));
  assert.equal(documentNode.defaultView.listenerCounts.get("hashchange"), 0);
  assert.equal(documentNode.defaultView.listenerCounts.get("keydown"), 0);
});

test("injected clients, generic actions, slots, and mounts stay isolated", async (t) => {
  const originalFetch = globalThis.fetch;
  const assetFetches = [];
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async (input) => {
    assetFetches.push(String(input));
    return response(200, {});
  };

  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/strategy";
  const firstRoot = documentNode.createElement("div");
  const secondRoot = documentNode.createElement("div");
  secondRoot.classList.add("universe-app-root");
  const firstClient = injectedClient("first");
  const secondClient = injectedClient("second");
  const topbarStartSlot = documentNode.createElement("aside");
  const topbarEndSlot = documentNode.createElement("aside");
  const navigationStartSlot = documentNode.createElement("aside");
  const navigationEndSlot = documentNode.createElement("aside");
  const contentBeforeSlot = documentNode.createElement("aside");
  const contentAfterSlot = documentNode.createElement("aside");
  const invoked = [];

  const firstMount = mountUniverseApp(firstRoot, {
    client: firstClient,
    capabilities: {
      flags: ["example"],
      data: { sample: 1 },
      actions: [
        {
          label: "Refresh",
          onInvoke: (option) => { invoked.push(["refresh", option]); },
        },
        {
          label: "Choose",
          options: [
            { id: "one", label: "One" },
            { id: "two", label: "Two", data: { ordinal: 2 } },
          ],
          onInvoke: (option) => { invoked.push(["choose", option]); },
        },
      ],
    },
    slots: {
      topbarStart: () => topbarStartSlot,
      topbarEnd: topbarEndSlot,
      navigationStart: navigationStartSlot,
      navigationEnd: navigationEndSlot,
      contentBefore: contentBeforeSlot,
      contentAfter: contentAfterSlot,
    },
  });
  const secondMount = mountUniverseApp(secondRoot, {
    client: secondClient,
    capabilities: { flags: ["opaque"], data: { untouched: true } },
  });
  await settle();

  assert.equal(documentNode.defaultView.listenerCounts.get("hashchange"), 2);
  // Host actions are not chrome: a mount carrying them draws nothing until
  // the Organization view asks for them, and the topbar never does.
  assert.equal(byClass(firstRoot, "capability-actions").length, 0);
  assert.equal(byClass(secondRoot, "capability-actions").length, 0);
  const firstHeader = byClass(firstRoot, "topbar")[0];
  const firstBrand = byClass(firstRoot, "yoke-header-brand")[0];
  // Search follows the brand; host chrome follows the flexible spacer.
  assert.equal(firstHeader.children[0], firstBrand);
  assert.ok(firstHeader.children[1].classList.contains("header-search"));
  assert.ok(firstHeader.children[2].classList.contains("header-spacer"));
  assert.equal(firstHeader.children[3], topbarStartSlot);
  assert.equal(firstHeader.children[firstHeader.children.length - 1],
    topbarEndSlot);
  // Neither local mount substitutes organization identity for its actor.
  assert.equal(byClass(firstRoot, "org-context").length, 0);
  assert.equal(byClass(secondRoot, "org-context").length, 0);
  assert.equal(byClass(secondRoot, "actor-chip").length, 1);
  const firstNavigation = byClass(firstRoot, "sidenav")[0];
  assert.equal(firstNavigation.children[0], navigationStartSlot);
  assert.equal(
    firstNavigation.children[firstNavigation.children.length - 1],
    navigationEndSlot,
  );
  assert.ok(firstNavigation.children.slice(1, -1).every(
    (node) => node.classList.contains("nav-link"),
  ));
  const firstShell = byClass(firstRoot, "shell")[0];
  assert.equal(firstShell.children[0], firstNavigation);
  const firstBody = firstShell.children[1];
  assert.ok(firstBody.classList.contains("workbench-body"));
  assert.equal(firstBody.children[0], contentBeforeSlot);
  assert.ok(firstBody.children[1].classList.contains("content"));
  assert.equal(firstBody.children[2], contentAfterSlot);
  assert.ok(firstShell.children[2].classList.contains("app-footer"));
  assert.ok(!allNodes(secondRoot).includes(topbarStartSlot));
  assert.ok(firstClient.requests.every(
    (request) => !secondClient.requests.includes(request),
  ));
  const strategyRequest = firstClient.requests.find(
    (request) => request.function === "strategy.surface.list",
  );
  assert.deepEqual(strategyRequest.target, {
    kind: "global", project_id: "first",
  });
  assert.equal(assetFetches.length, 2);

  // Organization renders the host actions as real buttons in the view:
  // the optionless action wears its own label, the optioned one wears one
  // button per option. The topbar stays bare either way.
  documentNode.defaultView.location.hash = "#/organization";
  documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  await settle();
  assert.equal(byClass(firstHeader, "capability-actions").length, 0);
  const firstContent = byClass(firstRoot, "content")[0];
  assert.equal(byClass(firstContent, "capability-actions").length, 1);
  const buttons = byClass(firstRoot, "capability-action");
  assert.deepEqual(buttons.map((node) => node.tagName),
    ["BUTTON", "BUTTON", "BUTTON"]);
  assert.deepEqual(buttons.map((node) => node.textContent),
    ["Refresh", "One", "Two"]);
  // The capabilities bag on the second mount carries no actions, so its
  // settings view draws no controls at all.
  assert.equal(byClass(secondRoot, "capability-action").length, 0);
  // Invocation happens inside the originating click, so host actions that
  // need transient user activation (a file picker) keep it.
  buttons[0].dispatchEvent(new Event("click"));
  assert.equal(invoked.length, 1);
  buttons[2].dispatchEvent(new Event("click"));
  assert.equal(invoked.length, 2);
  await settle();
  assert.equal(invoked[0][0], "refresh");
  assert.equal(invoked[0][1], undefined);
  assert.equal(invoked[1][0], "choose");
  assert.equal(invoked[1][1].id, "two");

  // Back on a scoped view so the teardown half below exercises a route
  // that reads through each mount's own client.
  documentNode.defaultView.location.hash = "#/strategy";
  documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  await settle();

  const firstCallsBeforeUnmount = firstClient.requests.length;
  const secondCallsBeforeHash = secondClient.requests.length;
  firstMount.unmount();
  for (const slot of (
    [topbarStartSlot, topbarEndSlot, navigationStartSlot,
      navigationEndSlot, contentBeforeSlot, contentAfterSlot]
  )) assert.equal(slot.parentNode, null);
  assert.equal(documentNode.defaultView.listenerCounts.get("hashchange"), 1);
  documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  await settle();
  assert.equal(firstClient.requests.length, firstCallsBeforeUnmount);
  assert.ok(secondClient.requests.length > secondCallsBeforeHash);

  secondMount.unmount();
  assert.equal(documentNode.defaultView.listenerCounts.get("hashchange"), 0);
  assert.ok(secondRoot.classList.contains("universe-app-root"));
});

test("header identity follows the host boundary and local actor", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const documentNode = new FakeDocument();
  const hostedRoot = documentNode.createElement("div");
  const hostedClient = injectedClient("hosted");
  const hostedMount = mountUniverseApp(hostedRoot, {
    client: hostedClient,
    currentActor: { id: 2, kind: "human", label: "ben" },
    slots: { topbarStart: documentNode.createElement("aside") },
  });
  const localRoot = documentNode.createElement("div");
  const localClient = injectedClient("local");
  const localMount = mountUniverseApp(localRoot, {
    client: localClient,
    slots: { topbarEnd: documentNode.createElement("aside") },
  });
  await settle();

  // Host org chrome in topbarStart replaces the app's own org naming — and
  // the org read exists only to fill that naming, so it is skipped too. The
  // actor chip is engine identity, not org chrome, and stays.
  assert.equal(byClass(hostedRoot, "org-context").length, 0);
  assert.equal(byClass(hostedRoot, "actor-chip").length, 1);
  assert.ok(hostedClient.requests.every(
    (request) => request.function !== "organizations.get",
  ));
  // An unrelated host slot does not replace local actor identity.
  assert.equal(byClass(localRoot, "org-context").length, 0);
  assert.equal(
    byClass(byClass(localRoot, "actor-chip")[0], "actor-name")[0].textContent,
    "local actor",
  );
  assert.ok(localClient.requests.every(
    (request) => request.function !== "organizations.get",
  ));

  hostedMount.unmount();
  localMount.unmount();
  assert.equal(documentNode.defaultView.listenerCounts.get("hashchange"), 0);
});
