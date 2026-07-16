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
  // The header wears the shared frame from shell.css rather than restating
  // its own height — the drift that made the app's bar and the marketing
  // site's 32px apart.
  assert.ok(topbar.classList.contains("yoke-app-header"));
  assert.ok(shellNode.classList.contains("shell"));
  assert.equal(byClass(root, "capability-actions").length, 0);
  const functionFetches = fetches.filter((entry) => entry.init);
  assert.ok(functionFetches.length >= 3);
  assert.ok(functionFetches.every(
    (entry) => entry.url === "/api/functions/call",
  ));
  const assetFetch = fetches.find((entry) => !entry.init);
  assert.match(assetFetch.url, /\/static\/yoke-wordmark\.svg$/);
  assert.doesNotMatch(assetFetch.url, /\/assets\//);
  assert.equal(documentNode.defaultView.listenerCounts.get("hashchange"), 1);

  mounted.unmount();
  mounted.unmount();
  assert.equal(root.children.length, 0);
  assert.ok(!root.classList.contains("universe-app-root"));
  assert.equal(documentNode.defaultView.listenerCounts.get("hashchange"), 0);
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
  assert.equal(byClass(firstRoot, "capability-actions").length, 1);
  assert.equal(byClass(secondRoot, "capability-actions").length, 0);
  const firstHeader = byClass(firstRoot, "topbar")[0];
  const firstBrand = byClass(firstRoot, "yoke-header-brand")[0];
  // The mark sits hard left no matter what a host injects beside it — a
  // host-supplied topbarStart slot must never be able to push the brand
  // toward center (this was live on stage: the platform's org switcher did
  // exactly that because the slot rendered before the brand).
  assert.equal(firstHeader.children[0], firstBrand);
  assert.equal(firstHeader.children[1], topbarStartSlot);
  assert.equal(firstHeader.children[firstHeader.children.length - 1],
    topbarEndSlot);
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
  assert.equal(firstShell.children[1], contentBeforeSlot);
  assert.ok(firstShell.children[2].classList.contains("content"));
  assert.equal(firstShell.children[3], contentAfterSlot);
  assert.ok(!allNodes(secondRoot).includes(topbarStartSlot));
  assert.ok(firstClient.requests.every(
    (request) => !secondClient.requests.includes(request),
  ));
  const strategyRequest = firstClient.requests.find(
    (request) => request.function === "strategy.doc.list",
  );
  assert.deepEqual(strategyRequest.target, {
    kind: "global", project_id: "first",
  });
  assert.equal(assetFetches.length, 2);

  const [button, select] = byClass(firstRoot, "capability-action");
  button.dispatchEvent(new Event("click"));
  assert.equal(invoked.length, 1);
  select.value = "1";
  select.dispatchEvent(new Event("change"));
  assert.equal(invoked.length, 2);
  await settle();
  assert.equal(invoked[0][0], "refresh");
  assert.equal(invoked[0][1], undefined);
  assert.equal(invoked[1][0], "choose");
  assert.equal(invoked[1][1].id, "two");

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

test("strategy rows render slug, title, and status", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/strategy";
  const root = documentNode.createElement("div");
  const requests = [];
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return { status: 200, envelope: { success: true, result: { name: "Yoke" } } };
      }
      if (request.function === "projects.list") {
        return { status: 200, envelope: { success: true, result: { rows: [{ id: 1, slug: "yoke", name: "Yoke" }] } } };
      }
      if (request.function === "strategy.doc.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              docs: [{ slug: "MISSION", title: "Mission statement", archived: false }],
            },
          },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };

  const mounted = mountUniverseApp(root, { client });
  await settle();

  // At the "all" default the docs read fans out per project, and each row
  // wears the slug of the project bucket that requested it.
  const cells = allNodes(root)
    .filter((node) => node.tagName === "TH" || node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells, [
    "slug", "project", "title", "status",
    "MISSION", "yoke", "Mission statement", "active",
  ]);
  assert.ok(requests.some((request) => request.function === "strategy.doc.list"));
  mounted.unmount();
});

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
  assert.equal(buildUniverseRoute("strategy", "abc 1"),
    "#/strategy?project=abc%201");
  assert.equal(buildUniverseRoute("unknown", null), "#/overview");
});

test("every nav destination declares how it takes project scope", () => {
  for (const view of ["items", "strategy", "overview", "inbox", "frontier"]) {
    assert.equal(universeNavScope(view), "multi");
  }
  for (const view of ["workflows", "github", "project-settings"]) {
    assert.equal(universeNavScope(view), "single");
  }
  for (const view of ["projects", "access", "templates", "universe-settings"]) {
    assert.equal(universeNavScope(view), "none");
  }
  // Members and Billing are hosted chrome the platform injects through a
  // slot, so the workbench's own nav does not route them at all.
  for (const hosted of ["#/members", "#/billing"]) {
    assert.deepEqual(parseUniverseRoute(hosted), {
      view: "overview", tab: null, detail: null, project: null,
    });
  }
});
