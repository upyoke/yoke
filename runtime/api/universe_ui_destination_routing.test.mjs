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
        return okEnvelope({
          rows: [{ id: 1, name: "Yoke", public_item_prefix: "YOK" }],
        });
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

test("a destination's second segment is a drill-in, and only where one exists", () => {
  // There is no facet segment left to compete with a drill-in: every facet
  // that earned a name is a destination with its own entry.
  for (const entry of NAV) assert.equal(entry.tabs, undefined, entry.id);
  // A drill-in renderer only hangs off a destination that exists.
  for (const viewId of Object.keys(DETAIL_RENDERERS)) {
    assert.ok(NAV.some((entry) => entry.id === viewId), viewId);
  }
});

test("routes round-trip, and an unknown view falls back without its segment", () => {
  assert.deepEqual(parseUniverseRoute("#/flows?project=3"), {
    view: "flows", tab: null, detail: null, project: "3",
  });
  assert.equal(buildUniverseRoute("flows", "3"), "#/flows?project=3");
  assert.deepEqual(parseUniverseRoute("#/deployments"), {
    view: "deployments", tab: null, detail: null, project: null,
  });
  // A second segment is a drill-in now, so it survives on a view that exists…
  assert.equal(parseUniverseRoute("#/qa-plans/7?project=2").detail, "7");
  // …and falls with the view when that view does not.
  const unknown = parseUniverseRoute("#/nonsense/7?project=2");
  assert.equal(unknown.view, NAV[0].id);
  assert.equal(unknown.detail, null);
  const removedInfrastructure = parseUniverseRoute("#/infrastructure?project=2");
  assert.equal(removedInfrastructure.view, NAV[0].id);
  assert.equal(removedInfrastructure.detail, null);
});

test("a deep-linked destination is the active nav item and keeps its scope", async (t) => {
  const client = deliveryClient();
  const { documentNode, root, mounted } = await mountAt(
    t, "#/environments?project=1", client,
  );

  // The facet IS the destination now, so it is what the sidebar lights.
  const activeNav = byClass(root, "nav-link")
    .filter((node) => node.classList.contains("active"));
  assert.equal(activeNav.length, 1);
  assert.equal(
    allNodes(activeNav[0])
      .find((node) => node.classList.contains("txt")).textContent,
    "Environments",
  );
  // No strip: its five facets are five entries in the sidebar.
  assert.deepEqual(byClass(root, "tab-link"), []);

  assert.equal(byClass(root, "stub-panel").length, 0);
  assert.equal(byClass(root, "scope-bar").length, 1);
  assert.deepEqual(
    byClass(root, "scope-chip").map((node) => node.textContent),
    ["All", "YOK"],
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
    documentNode.defaultView.location.hash, "#/environments?project=1",
  );
  mounted.unmount();
});

test("a destination's page head names the destination, not a parent view", async (t) => {
  const client = deliveryClient();
  const { root, mounted } = await mountAt(t, "#/deployments?project=1", client);

  const content = byClass(root, "content")[0];
  assert.ok(content.children[0].classList.contains("page-head"));
  assert.ok(content.children.every(
    (child) => !child.classList.contains("tab-bar"),
  ));
  const head = content.children[0];
  assert.equal(byClass(head, "title")[0].textContent, "Deployments");
  assert.equal(
    byClass(head, "subtitle")[0].textContent,
    "Each run of a flow against a target environment.",
  );
  mounted.unmount();
});

test("Runs fills from deployment runs, newest first, with grounded status pills", async (t) => {
  const requests = [];
  const runRow = (id, status, stage) => ({
    id, project: "yoke", flow: "yoke-hosted-production",
    target_tier: "persistent", target_environment: "prod",
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
        return okEnvelope({
          rows: [{ id: 1, name: "Yoke", public_item_prefix: "YOK" }],
        });
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
  const { root, mounted } = await mountAt(t, "#/deployments?project=1", client);

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
  assert.deepEqual(chips.map((chip) => chip.textContent), ["All", "YOK"]);
  assert.deepEqual(
    chips.map((chip) => chip.classList.contains("on")), [false, true],
  );
  assert.equal(byClass(root, "stub-panel").length, 0);

  // Newest run first in the one prototype table; engine-projected stages
  // render as compact segmented bars.
  const cells = allNodes(root).filter((node) => node.tagName === "TD");
  assert.deepEqual(
    cells.filter((cell, index) => index % 7 === 0)
      .map((cell) => cell.textContent),
    [
      "run-20260103-002", "run-20260103-001",
      "run-20260102-001", "run-20260101-001",
    ],
  );
  assert.equal(byClass(root, "delivery-run-stage").length, 8);

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
