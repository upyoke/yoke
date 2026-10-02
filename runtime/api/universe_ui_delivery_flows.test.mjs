import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  selectionRoute,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_selection_routes.js";
import {
  createProjectSelection,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_project_selection.js";
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

const FLOWS = [
  {
    id: "alpha-release", name: "Alpha Release", project: "alpha",
    status: "active", target_tier: "persistent", target_environment: "prod",
    on_failure: "halt", stages: [{ name: "build" }, { name: "verify" }],
    description: "Release Alpha to production.", supersedes_flow_id: "alpha-legacy",
  },
  {
    id: "alpha-legacy", name: "Alpha Legacy", project: "alpha",
    status: "disabled", target_tier: "persistent", target_environment: "stage",
    on_failure: "continue", stages: [{ name: "archive" }],
  },
  {
    id: "beta-promote", name: "Beta Promote", project: "beta",
    status: "active", target_tier: "ephemeral", target_environment: null,
    on_failure: "halt", stages: [{ name: "package" }, { name: "promote" }, { name: "observe" }],
  },
];

function flowClient(flows = FLOWS) {
  const requests = [];
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return okEnvelope({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return okEnvelope({ rows: [
          { id: 1, slug: "alpha", name: "Alpha" },
          { id: 2, slug: "beta", name: "Beta" },
        ] });
      }
      if (request.function === "deployment_runs.list") {
        const flow = request.payload.page.flow;
        return okEnvelope({ rows: flow === "alpha-release" ? RUNS : [] });
      }
      if (request.function === "workflows.definition.get") {
        const project = request.payload.project;
        const projectSlug = project === "1" ? "alpha" : project === "2" ? "beta" : null;
        return okEnvelope({
          flows: projectSlug
            ? flows.filter((row) => row.project === projectSlug)
            : flows,
        });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mountFlows(t, client, hash = "#/deployments/flows") {
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

test("Deployments opens on Flows under one route head", async (t) => {
  const { root, mounted } = await mountFlows(
    t, flowClient(), "#/deployments?project=1",
  );

  const head = byClass(root, "page-head")[0];
  assert.equal(byClass(head, "title")[0].textContent, "Deployments");
  const tabs = byClass(root, "tab-link");
  assert.deepEqual(tabs.map((tab) => tab.textContent), ["Flows", "Runs"]);
  // No tab segment means the first tab, and each tab links to its own route.
  assert.deepEqual(
    tabs.map((tab) => tab.classList.contains("active")), [true, false],
  );
  assert.deepEqual(tabs.map((tab) => tab.href), [
    "#/deployments/flows?project=1",
    "#/deployments/runs?project=1",
  ]);
  assert.equal(byClass(root, "panel-title")[0]?.textContent ?? "Flows", "Flows");
  mounted.unmount();
});

const RUNS = Array.from({ length: 6 }, (_, index) => ({
  id: `run-20260927-00${index + 1}`, project: "alpha", status: "succeeded",
  created_at: `2026-09-27T1${index}:00:00Z`,
}));

function rowNames(root) {
  return byClass(root, "delivery-flow-row-name").map((node) => node.textContent);
}

function detailHeading(root) {
  return byClass(root, "delivery-flow-detail-name")[0]?.textContent;
}

function rowFor(root, name) {
  return byClass(root, "delivery-flow-row").find(
    (row) => byClass(row, "delivery-flow-row-name")[0].textContent === name,
  );
}

function tagText(node, tag) {
  return allNodes(node).find((child) => child.tagName === tag)?.textContent;
}

test("the list groups active flows by project with full names and plain meta", async (t) => {
  const { root, mounted } = await mountFlows(t, flowClient());

  assert.deepEqual(rowNames(root), ["Alpha Release", "Beta Promote"]);
  assert.deepEqual(
    byClass(root, "delivery-flow-group").map((group) => tagText(group, "H3")),
    ["alpha", "beta"],
  );
  assert.deepEqual(
    byClass(root, "delivery-flow-row-meta").map((node) => node.textContent),
    ["prod · 2 stages", "3 stages"],
  );
  // Active flows carry no pill; the first flow is selected and highlighted.
  assert.equal(byClass(byClass(root, "delivery-flow-groups")[0], "pill").length, 0);
  const first = rowFor(root, "Alpha Release");
  assert.equal(first.classList.contains("is-selected"), true);
  assert.equal(first.attributes.get("aria-current"), "true");
  assert.equal(byClass(root, "delivery-flow-count")[0].textContent, "2 flows");
  assert.match(byClass(root, "delivery-flow-show-disabled")[0].textContent, /Show disabled \(1\)/);
  mounted.unmount();
});

test("Show disabled reveals disabled flows with a status pill", async (t) => {
  const { root, mounted } = await mountFlows(t, flowClient());
  const box = allNodes(byClass(root, "delivery-flow-show-disabled")[0])
    .find((node) => node.tagName === "INPUT");
  box.checked = true;
  box.dispatchEvent(new Event("change"));
  assert.deepEqual(rowNames(root), ["Alpha Release", "Alpha Legacy", "Beta Promote"]);
  assert.equal(byClass(rowFor(root, "Alpha Legacy"), "pill")[0].textContent, "disabled");
  mounted.unmount();
});

test("search matches names, ids, stages and environments", async (t) => {
  const { root, mounted } = await mountFlows(t, flowClient());
  const search = byClass(root, "delivery-flow-search")[0];
  for (const [query, expected] of [
    ["promote", ["Beta Promote"]],
    ["alpha-release", ["Alpha Release"]],
    ["observe", ["Beta Promote"]],
    ["prod", ["Alpha Release"]],
  ]) {
    search.value = query;
    search.dispatchEvent(new Event("input"));
    assert.deepEqual(rowNames(root), expected, query);
  }
  search.value = "nothing-here";
  search.dispatchEvent(new Event("input"));
  assert.equal(byClass(root, "delivery-flow-empty")[0].textContent, "No flows match.");
  mounted.unmount();
});

test("the selected flow shows its facts, the flow it replaces and recent runs", async (t) => {
  const client = flowClient();
  const { root, mounted } = await mountFlows(t, client, "#/deployments/flows?project=1");
  await settle();

  assert.equal(detailHeading(root), "Alpha Release");
  assert.equal(byClass(root, "delivery-flow-id")[0].textContent, "alpha-release");
  assert.equal(
    byClass(root, "delivery-flow-description")[0].textContent, "Release Alpha to production.",
  );
  const facts = byClass(root, "delivery-flow-fact").map((fact) => [
    tagText(fact, "DT"), tagText(fact, "DD"),
  ]);
  assert.deepEqual(facts, [
    ["Project", "alpha"], ["Environment", "prod"], ["Target tier", "persistent"],
    ["On failure", "halt"], ["Replaces", "Alpha Legacy"],
  ]);
  const replaces = byClass(root, "delivery-flow-replaces")[0];
  assert.equal(replaces.href, "#/deployments/flows/alpha-legacy?project=1");

  const runRequest = client.requests.find((request) => request.function === "deployment_runs.list");
  assert.deepEqual(runRequest.payload, {
    page: { page_size: 5, flow: "alpha-release", projects: ["alpha"] },
  });
  const runLinks = byClass(root, "delivery-flow-run-link");
  assert.equal(runLinks.length, 5);
  assert.equal(runLinks[0].textContent, "run-20260927-001");
  assert.match(runLinks[0].href, /^#\/deployments\/runs\/run-20260927-001/);

  // Following Replaces opens the replaced (disabled) flow in place.
  replaces.dispatchEvent(new Event("click", { cancelable: true }));
  assert.equal(detailHeading(root), "Alpha Legacy");
  assert.equal(rowFor(root, "Alpha Legacy").classList.contains("is-selected"), true);
  mounted.unmount();
});

test("choosing a flow opens it alone and All flows returns to the list", async (t) => {
  const { documentNode, root, mounted } = await mountFlows(t, flowClient());
  const page = byClass(root, "delivery-flow-page")[0];
  assert.equal(page.classList.contains("is-detail-open"), false);
  assert.equal(rowFor(root, "Beta Promote").tagName, "A");
  assert.match(rowFor(root, "Beta Promote").href, /flows\/beta-promote/);
  rowFor(root, "Beta Promote").dispatchEvent(new Event("click"));
  assert.equal(page.classList.contains("is-detail-open"), true);
  assert.equal(detailHeading(root), "Beta Promote");
  assert.match(documentNode.defaultView.location.hash, /flows\/beta-promote/);
  assert.equal(documentNode.activeElement, byClass(root, "delivery-flow-detail")[0]);
  const back = byClass(root, "delivery-flow-back")[0];
  assert.equal(back.textContent, "‹ All flows");
  back.dispatchEvent(new Event("click"));
  assert.equal(page.classList.contains("is-detail-open"), false);
  assert.equal(documentNode.activeElement, rowFor(root, "Beta Promote"));
  assert.doesNotMatch(documentNode.defaultView.location.hash, /beta-promote/);
  mounted.unmount();
});

test("Flows offers no way to create, edit, version or disable a definition", async (t) => {
  const client = flowClient();
  const { root, mounted } = await mountFlows(t, client);
  rowFor(root, "Beta Promote").dispatchEvent(new Event("click"));
  await settle();
  const labels = allNodes(root)
    .filter((node) => node.tagName === "BUTTON")
    .map((node) => node.textContent.trim());
  for (const forbidden of ["New flow", "Edit", "New version", "Disable", "Enable"]) {
    assert.equal(labels.includes(forbidden), false, forbidden);
  }
  for (const className of ["delivery-flow-action", "delivery-flow-form", "delivery-flow-actions"]) {
    assert.equal(byClass(root, className).length, 0, className);
  }
  const called = client.requests.map((request) => request.function);
  assert.equal(called.some((functionId) => functionId.startsWith("deployment_flows.")), false);
  mounted.unmount();
});

test("an empty scope points at the CLI rather than a form", async (t) => {
  const { root, mounted } = await mountFlows(t, flowClient([]));
  assert.match(byClass(root, "delivery-flow-empty")[0].textContent, /yoke deployment-flows create/);
  mounted.unmount();
});

test("Flows spans every readable project with the scoped project first and no title bar", async (t) => {
  const client = flowClient();
  const { root, mounted } = await mountFlows(t, client, "#/deployments/flows?project=2");
  assert.deepEqual(
    client.requests.filter((request) => request.function === "workflows.definition.get")
      .map((request) => request.payload),
    [{}],
  );
  assert.deepEqual(
    byClass(root, "delivery-flow-group").map((group) => tagText(group, "H3")),
    ["beta", "alpha"],
  );
  assert.equal(rowFor(root, "Beta Promote").classList.contains("is-selected"), true);
  const panel = byClass(root, "delivery-flow-panel")[0];
  assert.equal(byClass(panel, "panel-header").length, 0);
  mounted.unmount();
});

test("a server without description or lineage fields degrades to the facts it has", async (t) => {
  const bare = FLOWS.map(({ description, supersedes_flow_id, ...rest }) => rest);
  const { root, mounted } = await mountFlows(t, flowClient(bare));
  assert.equal(byClass(root, "delivery-flow-description").length, 0);
  assert.deepEqual(
    byClass(root, "delivery-flow-fact").map((fact) => tagText(fact, "DT")),
    ["Project", "Environment", "Target tier", "On failure"],
  );
  mounted.unmount();
});

test("a flow deep link opens the Flows tab on that definition", async (t) => {
  // The drill-in under the Flows tab is a definition, not a run.
  const { root, mounted } = await mountFlows(
    t, flowClient(), "#/deployments/flows/alpha-legacy?project=1",
  );
  assert.equal(detailHeading(root), "Alpha Legacy");
  // A retired definition is what the link named, so the list shows disabled
  // definitions rather than falling back to the first active flow.
  assert.equal(byClass(root, "delivery-flow-id")[0].textContent, "alpha-legacy");
  assert.equal(
    byClass(byClass(root, "delivery-flow-detail")[0], "pill")[0].textContent, "disabled",
  );
  assert.equal(byClass(root, "delivery-flow-page")[0].classList.contains("is-detail-open"), true);
  mounted.unmount();
});

test("a tabbed destination keeps its tab when the route is rebuilt", () => {
  // A scope change on a run page rebuilds the hash. The drill-in has to stay
  // in the second segment: putting it in the tab slot rewrote
  // `#/deployments/runs/<run id>` to `#/deployments/<run id>`, which still
  // drew the run and still lost the tab its breadcrumb returns to.
  const state = createProjectSelection(null);
  state.seed("deployments", ["1"]);
  assert.equal(
    selectionRoute(
      { view: "deployments", tab: "runs", detail: "run-20260726-001" },
      state, "1", "#/deployments/runs/run-20260726-001?project=1",
    ),
    "#/deployments/runs/run-20260726-001?project=1&selection=1",
  );
  // A tab with no drill-in keeps the tab and takes the remembered selection.
  assert.equal(
    selectionRoute({ view: "deployments", tab: "runs", detail: null }, state),
    "#/deployments/runs?project=1",
  );
  // An untabbed destination still spends its one segment on the drill-in.
  assert.equal(
    selectionRoute({ view: "items", tab: null, detail: "42" }, state, "2"),
    "#/items/42?project=2&selection=all",
  );
});
