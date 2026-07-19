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
  // With no host chrome in the header, the app names the org itself.
  const orgContextNodes = byClass(root, "org-context");
  assert.equal(orgContextNodes.length, 1);
  assert.equal(orgContextNodes[0].textContent, "Local");
  assert.ok(orgContextNodes[0].parentNode.classList.contains("context-side"));
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
  // Host actions are not chrome: a mount carrying them draws nothing until
  // the Organization view asks for them, and the topbar never does.
  assert.equal(byClass(firstRoot, "capability-actions").length, 0);
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
  // A header the host already stamps with its own org chrome must not name
  // the org a second time; the slotless mount beside it keeps naming it.
  assert.equal(byClass(firstRoot, "org-context").length, 0);
  const secondOrgContext = byClass(secondRoot, "org-context");
  assert.equal(secondOrgContext.length, 1);
  assert.equal(secondOrgContext[0].textContent, "second org");
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

test("a host-filled topbarStart suppresses the app's own org context", async (t) => {
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
  // Only topbarStart carries host org chrome: any other filled slot leaves
  // the app naming the org exactly as a slotless mount does.
  const localOrgContext = byClass(localRoot, "org-context");
  assert.equal(localOrgContext.length, 1);
  assert.equal(localOrgContext[0].textContent, "local org");
  assert.ok(localClient.requests.some(
    (request) => request.function === "organizations.get",
  ));

  hostedMount.unmount();
  localMount.unmount();
  assert.equal(documentNode.defaultView.listenerCounts.get("hashchange"), 0);
});

test("strategy rows render slug, title, owner, last write, size, and status", async (t) => {
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
              docs: [
                {
                  slug: "MISSION", title: "Mission statement",
                  updated_at: "2026-07-01", updated_by: "ben",
                  bytes: 2048, archived: false,
                },
                {
                  slug: "VISION", title: "Vision",
                  updated_at: "2026-06-30", updated_by: null,
                  bytes: 512, archived: true,
                },
              ],
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
  // wears the slug of the project bucket that requested it. The values pass
  // through as served: an unresolved editor renders empty, and the size is
  // the raw byte number the engine owns.
  const cells = allNodes(root)
    .filter((node) => node.tagName === "TH" || node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells, [
    "slug", "project", "title", "owner", "last write", "size", "status",
    "MISSION", "yoke", "Mission statement", "ben", "2026-07-01", "2048",
    "active",
    "VISION", "yoke", "Vision", "", "2026-06-30", "512", "archived",
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

test("host-fed sections light their nav entries and render as the view", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/members";
  const root = documentNode.createElement("div");
  const membersPanel = documentNode.createElement("section");
  const billingPanel = documentNode.createElement("section");
  const mounted = mountUniverseApp(root, {
    client: injectedClient("host"),
    // One section arrives as an element, the other through a factory: both
    // shapes of UniverseSlotContent materialize the same way.
    sections: { members: membersPanel, billing: () => billingPanel },
  });
  await settle();

  // Both host-fed entries join the one flat nav arc as ordinary links.
  const navLabels = byClass(root, "nav-link")
    .map((link) => link.children[1] && link.children[1].textContent);
  assert.ok(navLabels.includes("Members"));
  assert.ok(navLabels.includes("Billing"));

  // The routed host-fed view mounts the host's node as the whole body under
  // the entry's own page head — no picker, no stub.
  assert.ok(allNodes(root).includes(membersPanel));
  assert.equal(byClass(root, "title")[0].textContent, "Members");
  assert.equal(byClass(root, "scope-bar").length, 0);
  assert.equal(byClass(root, "stub-panel").length, 0);
  assert.ok(membersPanel.parentNode.classList.contains("view-host"));

  // Routing to the other host-fed view swaps sections and releases the
  // outgoing node completely — it never strands in a discarded subtree.
  documentNode.defaultView.location.hash = "#/billing";
  documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  await settle();
  assert.ok(allNodes(root).includes(billingPanel));
  assert.equal(membersPanel.parentNode, null);
  assert.equal(byClass(root, "title")[0].textContent, "Billing");

  // Unmount detaches the mounted section, leaving the node reusable.
  mounted.unmount();
  assert.equal(billingPanel.parentNode, null);
  assert.equal(membersPanel.parentNode, null);
});

test("a host-fed deep link without its section stays honest", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/members";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client: injectedClient("local") });
  await settle();

  // No supplied section, no nav entry: the arc carries no dead links.
  const navLabels = byClass(root, "nav-link")
    .map((link) => link.children[1] && link.children[1].textContent);
  assert.ok(!navLabels.includes("Members"));
  assert.ok(!navLabels.includes("Billing"));

  // The deep link still routes — the page head names the destination and
  // the body is the coming-soon stub, not a blank or a crash.
  assert.equal(byClass(root, "title")[0].textContent, "Members");
  assert.equal(byClass(root, "stub-panel").length, 1);

  mounted.unmount();
});

test("a section for a workbench view appends after the view's own output", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/strategy";
  const root = documentNode.createElement("div");
  const extra = documentNode.createElement("aside");
  const mounted = mountUniverseApp(root, {
    client: injectedClient("host"),
    sections: { strategy: extra },
  });
  await settle();

  // The view renders itself first; the host's section lands after it,
  // inside the same view host.
  const viewHost = byClass(root, "view-host")[0];
  assert.ok(viewHost.children.length >= 2);
  assert.ok(viewHost.children[0].classList.contains("panel"));
  assert.equal(viewHost.children[viewHost.children.length - 1], extra);

  // A section never turns a workbench view into a nav toggle: strategy's
  // entry was in the arc before the section and stays exactly once.
  const strategyLinks = byClass(root, "nav-link").filter(
    (link) => link.children[1] && link.children[1].textContent === "Strategy",
  );
  assert.equal(strategyLinks.length, 1);

  // Leaving the view releases the section node; unmount keeps it released.
  documentNode.defaultView.location.hash = "#/items";
  documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  await settle();
  assert.equal(extra.parentNode, null);
  mounted.unmount();
  assert.equal(extra.parentNode, null);
});

test("host sections remain visible when a single-scope view has no project", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  // GitHub is the single-scope view that renders an engine-backed read, so
  // it is the one that reaches the empty-universe panel; a scope-less or
  // unbuilt view never gets there.
  for (const placement of ["inView", "beforeScope"]) {
    const documentNode = new FakeDocument();
    documentNode.defaultView.location.hash = "#/github";
    const root = documentNode.createElement("div");
    const hostSection = documentNode.createElement("aside");
    const client = {
      async call(request) {
        if (request.function === "organizations.get") {
          return { status: 200, envelope: { success: true, result: { name: "Empty" } } };
        }
        if (request.function === "projects.list") {
          return { status: 200, envelope: { success: true, result: { rows: [] } } };
        }
        throw new Error(`unexpected function ${request.function}`);
      },
    };
    const mounted = mountUniverseApp(root, {
      client, sections: { github: { content: hostSection, placement } },
    });
    await settle();

    // Project scope governs the engine-owned read, not the host's section.
    // Org-plane controls such as the hosted GitHub connection must remain
    // reachable before the universe has its first project — at either
    // placement, because an empty universe draws no picker for a
    // `beforeScope` section to sit above.
    assert.equal(byClass(root, "empty")[0].textContent, "no projects yet", placement);
    assert.ok(allNodes(root).includes(hostSection), placement);
    const viewHost = byClass(root, "view-host")[0];
    assert.equal(
      viewHost.children[viewHost.children.length - 1], hostSection, placement,
    );

    mounted.unmount();
    assert.equal(hostSection.parentNode, null, placement);
  }
});

test("a beforeScope section sits above the picker, an inView section below", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const mountWith = async (placement) => {
    const documentNode = new FakeDocument();
    documentNode.defaultView.location.hash = "#/github?project=1";
    const root = documentNode.createElement("div");
    const hostSection = documentNode.createElement("aside");
    const client = {
      async call(request) {
        if (request.function === "organizations.get") {
          return { status: 200, envelope: { success: true, result: { name: "Org" } } };
        }
        if (request.function === "projects.list") {
          return {
            status: 200,
            envelope: { success: true, result: { rows: [{ id: 1, slug: "a", name: "A" }] } },
          };
        }
        return { status: 200, envelope: { success: true, result: { bound: false } } };
      },
    };
    const mounted = mountUniverseApp(root, {
      client, sections: { github: { content: hostSection, placement } },
    });
    await settle();
    return { root, hostSection, mounted };
  };

  // The hosted org's GitHub connection is not a project's fact, so the
  // picker must not appear to filter it: the section stands above the
  // control, between the page head and the chips.
  const above = await mountWith("beforeScope");
  const aboveContent = byClass(above.root, "content")[0];
  const aboveOrder = aboveContent.children.map((node) => node.className);
  assert.deepEqual(aboveOrder, ["page-head", "", "scope-bar", "view-host"]);
  assert.equal(aboveContent.children[1], above.hostSection);
  assert.ok(!allNodes(byClass(above.root, "view-host")[0])
    .includes(above.hostSection));
  above.mounted.unmount();

  // The default placement is unchanged: scoped content stays in the view,
  // under the picker, after whatever the view rendered for itself.
  const below = await mountWith("inView");
  const belowContent = byClass(below.root, "content")[0];
  assert.deepEqual(
    belowContent.children.map((node) => node.className),
    ["page-head", "scope-bar", "view-host"],
  );
  const belowHost = byClass(below.root, "view-host")[0];
  assert.equal(belowHost.children[belowHost.children.length - 1],
    below.hostSection);
  below.mounted.unmount();
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

test("a section entry is told from a spec by being a node, not by its keys", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/members";
  const root = documentNode.createElement("div");
  // A <template> owns a `content` property of its own, so an entry sniffed
  // for a `content` key would read this Element as a placement spec and hand
  // mount its DocumentFragment instead of the element the host supplied.
  const template = documentNode.createElement("template");
  template.content = new FakeNode(documentNode, "fragment", 11);

  const mounted = mountUniverseApp(root, {
    client: injectedClient("unused"), sections: { members: template },
  });
  await settle();

  assert.ok(allNodes(root).includes(template));
  mounted.unmount();
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
  for (const view of ["items", "strategy", "overview", "inbox", "frontier"]) {
    assert.equal(universeNavScope(view), "multi");
  }
  for (const view of ["github", "project", "packs"]) {
    assert.equal(universeNavScope(view), "single");
  }
  // Workflows serves the engine's universe-wide lifecycle definition, so no
  // project narrows it and it draws no picker.
  for (const view of ["projects", "access", "organization", "workflows"]) {
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
