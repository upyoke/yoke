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

test("a host-fed section lights its nav entry and renders as the view", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = "/billing";
  const root = documentNode.createElement("div");
  const billingPanel = documentNode.createElement("section");
  const seatsPanel = documentNode.createElement("section");
  const mounted = mountUniverseApp(root, {
    client: injectedClient("host"),
    // One section arrives through a factory, the other as an element in a
    // spec: both shapes materialize the same way.
    sections: {
      billing: () => billingPanel,
      team: { content: seatsPanel, placement: "beforeScope" },
    },
  });
  await settle();

  // The host-fed entry joins the one flat nav arc; Team is the only people
  // destination, so no Members entry appears.
  const navLabels = byClass(root, "nav-link")
    .map((link) => link.children[1] && link.children[1].textContent);
  assert.ok(navLabels.includes("Billing"));
  assert.ok(navLabels.includes("Team"));
  assert.ok(!navLabels.includes("Members"));

  // The routed host-fed view mounts the host's node as the whole body under
  // the entry's page head. Host-fed destinations are unscoped, so the
  // project selector stays hidden.
  assert.ok(allNodes(root).includes(billingPanel));
  assert.equal(byClass(root, "title")[0].textContent, "Billing");
  assert.equal(byClass(root, "scope-bar").length, 0);
  assert.equal(byClass(root, "stub-panel").length, 0);
  assert.ok(billingPanel.parentNode.classList.contains("view-host"));

  // Team's beforeScope section leads the page, between the page head and
  // the view's own content, and the outgoing Billing node is released.
  documentNode.defaultView.location.href = "/team";
  documentNode.defaultView.dispatchEvent(new Event("popstate"));
  await settle();
  const viewHost = byClass(root, "view-host")[0];
  assert.equal(viewHost.parentNode.children[1], seatsPanel);
  assert.equal(viewHost.parentNode.children[2], viewHost);
  assert.ok(!allNodes(viewHost).includes(seatsPanel));
  assert.equal(billingPanel.parentNode, null);
  assert.equal(byClass(root, "title")[0].textContent, "Team");

  // Unmount detaches the mounted section, leaving the node reusable.
  mounted.unmount();
  assert.equal(billingPanel.parentNode, null);
  assert.equal(seatsPanel.parentNode, null);
});

test("a host-fed deep link without its section stays honest", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = "/billing";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client: injectedClient("local") });
  await settle();

  // No supplied section, no nav entry: the arc carries no dead links.
  const navLabels = byClass(root, "nav-link")
    .map((link) => link.children[1] && link.children[1].textContent);
  assert.ok(!navLabels.includes("Billing"));

  // The deep link still routes — the page head names the destination and
  // the body is the coming-soon stub, not a blank or a crash.
  assert.equal(byClass(root, "title")[0].textContent, "Billing");
  assert.equal(byClass(root, "stub-panel").length, 1);

  mounted.unmount();
});

test("a link to the retired Members path opens Team", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = "/members";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client: injectedClient("host") });
  await settle();

  assert.equal(byClass(root, "title")[0].textContent, "Team");
  assert.equal(new URL(documentNode.defaultView.location.href, "http://x").pathname, "/team");
  mounted.unmount();
});

test("a section for a workbench view appends after the view's own output", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = "/strategy";
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
  assert.ok(viewHost.children.some(
    (child) => child.classList.contains("work-band"),
  ));
  assert.equal(viewHost.children[viewHost.children.length - 1], extra);

  // A section never turns a workbench view into a nav toggle: strategy's
  // entry was in the arc before the section and stays exactly once.
  const strategyLinks = byClass(root, "nav-link").filter(
    (link) => link.children[1] && link.children[1].textContent === "Strategy",
  );
  assert.equal(strategyLinks.length, 1);

  // Leaving the view releases the section node; unmount keeps it released.
  documentNode.defaultView.location.href = "/items";
  documentNode.defaultView.dispatchEvent(new Event("popstate"));
  await settle();
  assert.equal(extra.parentNode, null);
  mounted.unmount();
  assert.equal(extra.parentNode, null);
});

test("host sections remain visible when GitHub has no project yet", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  // GitHub fans out across the picker, so an empty universe still renders
  // the view; the host section must stay reachable before the first
  // project — at either placement, because an empty universe draws no
  // picker for a `beforeScope` section to sit above.
  for (const placement of ["inView", "beforeScope"]) {
    const documentNode = new FakeDocument();
    documentNode.defaultView.location.href = "/github";
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
        if (request.function === "machine.list") {
          return { status: 200, envelope: { success: true, result: { machines: [], count: 0 } } };
        }
        throw new Error(`unexpected function ${request.function}`);
      },
    };
    const mounted = mountUniverseApp(root, {
      client, sections: { github: { content: hostSection, placement } },
    });
    await settle();

    assert.ok(allNodes(root).includes(hostSection), placement);
    const viewHost = byClass(root, "view-host")[0];
    if (placement === "inView") {
      assert.equal(
        viewHost.children[viewHost.children.length - 1], hostSection, placement,
      );
    } else {
      assert.ok(!allNodes(viewHost).includes(hostSection), placement);
    }

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
    documentNode.defaultView.location.href = "/github?project=1";
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
  // section remains above project-scoped view content while the picker lives
  // in the labelled header context.
  const above = await mountWith("beforeScope");
  const aboveContent = byClass(above.root, "content")[0];
  const aboveOrder = aboveContent.children.map((node) => node.className);
  assert.deepEqual(
    aboveOrder,
    ["page-head", "", "view-above-scope", "view-host"],
  );
  assert.equal(aboveContent.children[1], above.hostSection);
  assert.ok(byClass(above.root, "scope-bar")[0].parentNode.classList
    .contains("header-scope-host"));
  assert.ok(!allNodes(byClass(above.root, "view-host")[0])
    .includes(above.hostSection));
  above.mounted.unmount();

  // The default placement stays in the view after its own content.
  const below = await mountWith("inView");
  const belowContent = byClass(below.root, "content")[0];
  assert.deepEqual(
    belowContent.children.map((node) => node.className),
    ["page-head", "view-above-scope", "view-host"],
  );
  const belowHost = byClass(below.root, "view-host")[0];
  assert.equal(belowHost.children[belowHost.children.length - 1],
    below.hostSection);
  below.mounted.unmount();
});

test("a section entry is told from a spec by being a node, not by its keys", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = "/billing";
  const root = documentNode.createElement("div");
  // A <template> owns a `content` property of its own, so an entry sniffed
  // for a `content` key would read this Element as a placement spec and hand
  // mount its DocumentFragment instead of the element the host supplied.
  const template = documentNode.createElement("template");
  template.content = new FakeNode(documentNode, "fragment", 11);

  const mounted = mountUniverseApp(root, {
    client: injectedClient("unused"), sections: { billing: template },
  });
  await settle();

  assert.ok(allNodes(root).includes(template));
  mounted.unmount();
});
