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

test("Runs at All reads unfiltered and labels each run's own project", async (t) => {
  const requests = [];
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return okEnvelope({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return okEnvelope({
          rows: [
            { id: 1, slug: "yoke", name: "Yoke" },
            { id: 2, slug: "externalwebapp", name: "ExternalWebapp" },
          ],
        });
      }
      if (request.function === "deployment_runs.list") {
        return okEnvelope({
          rows: [{
            id: "run-20260101-001", project: "externalwebapp",
            flow: "externalwebapp-prod-release", target_env: "prod",
            release_lineage: null, status: "succeeded",
            current_stage: "complete", created_at: "then",
            started_at: null, completed_at: null, created_by: "usher",
          }],
        });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const { root, mounted } = await mountAt(t, "#/delivery/runs", client);

  // "all" is one unfiltered call over the whole universe.
  assert.deepEqual(
    requests.find((request) => request.function === "deployment_runs.list"),
    { function: "deployment_runs.list", payload: {} },
  );
  const headers = allNodes(root)
    .filter((node) => node.tagName === "TH")
    .map((node) => node.textContent);
  assert.deepEqual(headers, [
    "run", "project", "flow", "target", "stage", "status", "created",
  ]);
  const firstCells = allNodes(root)
    .filter((node) => node.tagName === "TD")
    .slice(0, 2)
    .map((node) => node.textContent ||
      (node.children[0] && node.children[0].textContent) || "");
  assert.deepEqual(firstCells, ["run-20260101-001", "externalwebapp"]);
  mounted.unmount();
});

// Flows moved here off the Workflows screen: a flow belongs to one project,
// so unlike the lifecycle definition it left behind, it takes the Delivery
// scope and fans out per project the way every other multi view does.
test("the Flows facet reads the served flows and takes the Delivery scope", async (t) => {
  const requests = [];
  const flowsByProject = {
    "1": [{
      id: "alpha-release", name: "Alpha Release", target_env: "prod",
      status: "active", on_failure: "halt",
      stage_names: ["build", "verify"], project: "alpha",
    }],
    "2": [{
      id: "beta-release", name: "Beta Release", target_env: "stage",
      status: "disabled", on_failure: "continue",
      stage_names: ["build"], project: "beta",
    }],
  };
  const client = {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") return okEnvelope({ name: "Yoke" });
      if (request.function === "projects.list") {
        return okEnvelope({
          rows: [
            { id: 1, slug: "alpha", name: "Alpha" },
            { id: 2, slug: "beta", name: "Beta" },
          ],
        });
      }
      if (request.function === "workflows.definition.get") {
        return okEnvelope({ flows: flowsByProject[request.payload.project] || [] });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  // No project in the route: Delivery is a multi view, so this is "all".
  const { root, mounted } = await mountAt(t, "#/delivery/flows", client);

  // "all" reads the whole universe in one unfiltered call, and the flows the
  // engine serves already carry the project each belongs to.
  assert.deepEqual(
    requests.filter((request) => request.function === "workflows.definition.get"),
    [{ function: "workflows.definition.get", payload: {} }],
  );
  // A built facet carries its own picker.
  assert.equal(byClass(root, "scope-bar").length, 1);
  assert.equal(byClass(root, "stub-panel").length, 0);
  mounted.unmount();

  // Narrowed to one project, the read names it and the project column drops:
  // every row belongs to the one project the picker holds.
  const scoped = await mountAt(t, "#/delivery/flows?project=2", client);
  const headers = allNodes(scoped.root)
    .filter((node) => node.tagName === "TH")
    .map((node) => node.textContent);
  assert.deepEqual(headers, [
    "flow", "name", "target env", "status", "stages", "on failure",
  ]);
  const cells = allNodes(scoped.root)
    .filter((node) => node.tagName === "TD")
    .map((node) => node.textContent ||
      (node.children[0] && node.children[0].textContent) || "");
  assert.deepEqual(cells, [
    "beta-release", "Beta Release", "stage", "disabled", "build", "continue",
  ]);
  scoped.mounted.unmount();
});

test("every unbuilt Delivery tab renders the stub treatment and never a picker", async (t) => {
  for (const tabId of ["environments", "databases", "infrastructure"]) {
    const client = deliveryClient();
    const { root, mounted } = await mountAt(
      t, `#/delivery/${tabId}?project=1`, client,
    );
    assert.equal(byClass(root, "stub-panel").length, 1, tabId);
    assert.equal(byClass(root, "scope-chip").length, 0, tabId);
    assert.ok(
      !client.requests.some(
        (request) => request.function === "deployment_runs.list",
      ),
      tabId,
    );
    mounted.unmount();
  }
});
