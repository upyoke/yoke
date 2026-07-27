import assert from "node:assert/strict";
import test from "node:test";

import {
  buildUniverseRoute,
  mountUniverseApp,
  parseUniverseRoute,
} from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  NAV,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_navigation.js";
import {
  DETAIL_RENDERERS,
  TAB_RENDERERS,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function okEnvelope(result) {
  return { status: 200, envelope: { success: true, result } };
}

// The shell reads plus an empty runs table — enough for any Delivery facet.
function deliveryClient() {
  const requests = [];
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return okEnvelope({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return okEnvelope({ rows: [{ id: 1, name: "Yoke" }] });
      }
      if (request.function === "deployment_runs.list") {
        return okEnvelope({ rows: [] });
      }
      if (request.function === "projects.infrastructure.list") {
        return okEnvelope({
          project: request.payload.project,
          sites: [],
          environments: [],
        });
      }
      if (request.function === "projects.capabilities.list") {
        return okEnvelope({ rows: [] });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mountAt(t, hash, client) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { documentNode, root, mounted };
}

test("a view declares its second segment — tabs or drill-in, never both", () => {
  const tabbed = NAV.filter((entry) => entry.tabs);
  assert.ok(tabbed.length > 0);
  for (const entry of tabbed) {
    assert.ok(entry.tabs.length > 0);
    // The same segment cannot be a tab and a drill-in at once.
    assert.ok(!(entry.id in DETAIL_RENDERERS), entry.id);
    // Every unbuilt tab must say what it will be.
    for (const tab of entry.tabs) {
      const live = Boolean((TAB_RENDERERS[entry.id] || {})[tab.id]);
      assert.ok(live || tab.summary, `${entry.id}/${tab.id}`);
    }
    // A live tab renderer must belong to a declared tab.
    for (const tabId of Object.keys(TAB_RENDERERS[entry.id] || {})) {
      assert.ok(entry.tabs.some((tab) => tab.id === tabId), tabId);
    }
  }
  // Tab renderers only hang off views that declared tabs.
  for (const viewId of Object.keys(TAB_RENDERERS)) {
    assert.ok(NAV.some((entry) => entry.id === viewId && entry.tabs), viewId);
  }
});

test("tab routes round-trip; absent and unknown segments resolve to the first tab", () => {
  assert.deepEqual(parseUniverseRoute("#/delivery/flows?project=3"), {
    view: "delivery", tab: "flows", detail: null, project: "3",
  });
  assert.equal(
    buildUniverseRoute("delivery", "3", "flows"),
    "#/delivery/flows?project=3",
  );
  assert.deepEqual(parseUniverseRoute("#/delivery"), {
    view: "delivery", tab: "runs", detail: null, project: null,
  });
  assert.equal(parseUniverseRoute("#/delivery/nonsense?project=2").tab, "runs");
  // A tabbed view's segment is a facet, never a drill-in detail — so an
  // unknown segment resolves instead of surviving as a detail.
  assert.equal(parseUniverseRoute("#/delivery/flows").detail, null);
});

test("a deep-linked Delivery facet stays under the active nav item and keeps scope", async (t) => {
  const client = deliveryClient();
  const { documentNode, root, mounted } = await mountAt(
    t, "#/delivery/environments?project=1", client,
  );

  // Delivery stays the active destination; the tab never becomes one.
  const activeNav = byClass(root, "nav-link")
    .filter((node) => node.classList.contains("active"));
  assert.equal(activeNav.length, 1);
  assert.equal(
    allNodes(activeNav[0])
      .find((node) => node.classList.contains("txt")).textContent,
    "Delivery",
  );

  const tabLinks = byClass(root, "tab-link");
  assert.deepEqual(
    tabLinks.map((node) => node.textContent),
    ["Runs", "Environments", "Flows", "Databases", "Infrastructure"],
  );
  const activeTabs = tabLinks
    .filter((node) => node.classList.contains("active"));
  assert.equal(activeTabs.length, 1);
  assert.equal(activeTabs[0].textContent, "Environments");
  // Tabs are real links that carry the view's scope.
  assert.equal(activeTabs[0].href, "#/delivery/environments?project=1");

  assert.equal(byClass(root, "stub-panel").length, 0);
  assert.equal(byClass(root, "scope-bar").length, 1);
  assert.deepEqual(
    byClass(root, "scope-chip").map((node) => node.textContent),
    ["All", "Yoke"],
  );
  assert.deepEqual(
    client.requests.filter((request) => (
      request.function === "projects.infrastructure.list" ||
      request.function === "deployment_runs.list"
    )),
    [
      {
        function: "projects.infrastructure.list",
        payload: { project: "1" },
      },
      { function: "deployment_runs.list", payload: { project: "1" } },
    ],
  );
  // The deep link survives untouched.
  assert.equal(
    documentNode.defaultView.location.hash, "#/delivery/environments?project=1",
  );
  mounted.unmount();
});

test("a tabbed view's page head names the view and holds still across facets", async (t) => {
  const client = deliveryClient();
  const { documentNode, root, mounted } = await mountAt(
    t, "#/delivery/runs?project=1", client,
  );

  const headOf = (node) => {
    const content = byClass(node, "content")[0];
    // The head leads the content column. Built facets put project scope
    // before the strip; stubs omit the scope picker.
    assert.ok(content.children[0].classList.contains("page-head"));
    assert.ok(content.children.some(
      (child) => child.classList.contains("tab-bar"),
    ));
    return content.children[0];
  };

  const liveHead = headOf(root);
  const liveContent = byClass(root, "content")[0];
  assert.ok(liveContent.children[1].classList.contains("scope-bar"));
  assert.ok(liveContent.children[2].classList.contains("tab-bar"));
  assert.equal(byClass(liveHead, "title")[0].textContent, "Delivery");
  assert.equal(
    byClass(liveHead, "subtitle")[0].textContent,
    "Environments, flows and runs, with databases and infrastructure.",
  );

  // Switching to another live facet re-renders the same head: one concept,
  // one name, whatever the strip below shows.
  documentNode.defaultView.location.hash = "#/delivery/environments?project=1";
  documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  await settle();
  assert.equal(byClass(root, "stub-panel").length, 0);
  const stubHead = headOf(root);
  assert.equal(byClass(root, "page-head").length, 1);
  assert.equal(byClass(stubHead, "title")[0].textContent, "Delivery");
  assert.equal(
    byClass(stubHead, "subtitle")[0].textContent,
    "Environments, flows and runs, with databases and infrastructure.",
  );
  mounted.unmount();
});

test("a tabbed route with no segment renders its first tab without rewriting the hash", async (t) => {
  const client = deliveryClient();
  const { documentNode, root, mounted } = await mountAt(
    t, "#/delivery?project=1", client,
  );

  const activeTabs = byClass(root, "tab-link")
    .filter((node) => node.classList.contains("active"));
  assert.equal(activeTabs.length, 1);
  assert.equal(activeTabs[0].textContent, "Runs");
  // Resolution is a render decision, not a URL mutation: the bare route
  // stays shareable exactly as the viewer wrote it.
  assert.equal(
    documentNode.defaultView.location.hash, "#/delivery?project=1",
  );
  mounted.unmount();
});

test("Runs fills from deployment runs, newest first, with grounded status pills", async (t) => {
  const requests = [];
  const runRow = (id, status, stage) => ({
    id, project: "yoke", flow: "yoke-hosted-production", target_env: "production",
    release_lineage: null, status, current_stage: stage,
    created_at: `${id}-created`, started_at: null, completed_at: null,
    created_by: "usher",
    stage_index: stage ? 1 : -1,
    stage_count: 2,
    stages: [
      { name: "build", state: status === "created" ? "active" : "complete" },
      {
        name: stage || "release",
        state: status === "failed"
          ? "failed" : (status === "succeeded" ? "complete" : "active"),
      },
    ],
    member_items: [],
    waiting_on_approval: false,
  });
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return okEnvelope({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return okEnvelope({ rows: [{ id: 1, name: "Yoke" }] });
      }
      if (request.function === "deployment_runs.list") {
        // Engine order: newest first.
        return okEnvelope({
          rows: [
            runRow("run-20260103-002", "executing", "ci-gate"),
            runRow("run-20260103-001", "created", null),
            runRow("run-20260102-001", "failed", "test-failed"),
            runRow("run-20260101-001", "succeeded", "complete"),
          ],
        });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const { root, mounted } = await mountAt(t, "#/delivery/runs?project=1", client);

  // The read carries the view's scope in the payload and keeps the proxy's
  // server-side global target default.
  assert.deepEqual(
    requests.find((request) => request.function === "deployment_runs.list"),
    { function: "deployment_runs.list", payload: { project: "1" } },
  );

  // A built tab carries its own picker: the All chip plus one per project,
  // with the routed project's chip marked selected.
  assert.equal(byClass(root, "scope-bar").length, 1);
  const chips = byClass(root, "scope-chip");
  assert.deepEqual(chips.map((chip) => chip.textContent), ["All", "Yoke"]);
  assert.deepEqual(
    chips.map((chip) => chip.classList.contains("on")), [false, true],
  );
  assert.equal(byClass(root, "stub-panel").length, 0);

  // Newest run first; the engine-projected stages render as a segmented bar.
  const cards = byClass(root, "delivery-run-card");
  assert.deepEqual(
    cards.map((card) => allNodes(card)
      .find((node) => node.tagName === "H3").textContent),
    [
      "run-20260103-002", "run-20260103-001",
      "run-20260102-001", "run-20260101-001",
    ],
  );
  assert.equal(byClass(cards[0], "delivery-stage").length, 2);

  // Grounded status vocabulary maps to semantic pill families; values the
  // hint has not seen (created) wear neutral idle.
  const pillFamilies = Object.fromEntries(
    byClass(root, "pill").map((node) => [
      node.attributes.get("data-state"),
      node.className.replace("pill", "").trim(),
    ]),
  );
  assert.deepEqual(pillFamilies, {
    executing: "run",
    succeeded: "good",
    failed: "crit",
    created: "idle",
  });
  mounted.unmount();
});
