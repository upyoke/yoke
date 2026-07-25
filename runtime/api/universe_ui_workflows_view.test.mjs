import assert from "node:assert/strict";
import test from "node:test";

import {
  mountUniverseApp,
} from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  cellText,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function okEnvelope(result) {
  return { status: 200, envelope: { success: true, result } };
}

// Invented registry vocabulary proves the view renders served definitions,
// labels, placements, catalog strings, and policy rather than client constants.
function definitionFixture(flows) {
  return {
    family: "work-items",
    workflows: [{
      id: "rally",
      name: "Rally",
      description: "Coordinate a small release train.",
      source: "pack",
      status: "disabled",
      current_version: 3,
      versions: [{ version: 1 }, { version: 3 }],
      definition: {
        stages: [
          { id: "draft", label: "Drafted", gates: [] },
          {
            id: "prove", label: "Proving",
            gates: [{ id: "evidence_check", mode: "strict" }],
            description: "Collect the declared proof.",
          },
          { id: "ship", label: "Shipped", gates: [] },
        ],
        policies: {
          ownership: "paired",
          item_knobs: ["extra proof", "approval"],
        },
      },
    }],
    gate_catalog: [
      {
        id: "evidence_check",
        name: "Evidence check",
        source_kind: "status_gate",
        availability: "live",
        description: "The declared proof must exist.",
      },
    ],
    flows,
  };
}

function workflowsClient(flows) {
  const requests = [];
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return okEnvelope({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return okEnvelope({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      if (request.function === "workflows.definition.get") {
        return okEnvelope(definitionFixture(flows));
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mountWorkflows(t, client) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/workflows";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { root, mounted };
}

function panelTitles(root) {
  return allNodes(root)
    .filter((node) => node.tagName === "H2")
    .map((node) => node.textContent);
}

test("Workflows renders the registry from one served read", async (t) => {
  const client = workflowsClient([
    {
      id: "demo-release", name: "Demo Release", target_env: "prod",
      status: "disabled", on_failure: "halt",
      stage_names: ["build", "verify"], project: "yoke",
    },
  ]);
  const { root, mounted } = await mountWorkflows(t, client);

  // The definition is universe-wide, so the read names no project at all.
  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "workflows.definition.get",
    ),
    { function: "workflows.definition.get", payload: {} },
  );
  assert.deepEqual(
    panelTitles(root),
    ["Workflows", "Stages", "Gate catalog", "Posture"],
  );

  // Nothing on this screen takes a project, so it draws no picker — and no
  // note explaining a picker that is not there.
  assert.equal(byClass(root, "scope-bar").length, 0);
  assert.equal(byClass(root, "scope-chip").length, 0);
  assert.equal(byClass(root, "view-note").length, 0);

  const cells = allNodes(root)
    .filter((node) => node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells, [
    "Rally", "rally", "v3", "v1 · v3", "disabled", "pack",
    "Coordinate a small release train.",
    "Rally", "1/3", "draft", "Drafted", "", "",
    "Rally", "2/3", "prove", "Proving", "evidence_check:strict",
    "Collect the declared proof.",
    "Rally", "3/3", "ship", "Shipped", "", "",
    "evidence_check", "Evidence check", "status_gate", "live",
    "The declared proof must exist.",
    "Rally", "ownership", "paired",
    "Rally", "item_knobs", "extra proof · approval",
  ]);

  // The cells above are the whole rendered table set, so the served flows
  // reach no row here — they belong to Delivery's Flows facet. (The panels'
  // raw-JSON toggles still carry them: that shows the response envelope the
  // panel rendered from, verbatim, which is the point of the toggle.)
  const rendered = allNodes(root).filter(
    (node) => node.tagName === "TD" && cellText(node).includes("demo-release"),
  );
  assert.deepEqual(rendered, []);
  mounted.unmount();
});

test("a failed read fails every panel instead of sticking at loading", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/workflows";
  const root = documentNode.createElement("div");
  const client = {
    async call(request) {
      if (request.function === "organizations.get") {
        return okEnvelope({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return okEnvelope({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      return {
        status: 500,
        envelope: { success: false, error: { message: "definition read broke" } },
      };
    },
  };
  const mounted = mountUniverseApp(root, { client });
  await settle();

  const errors = byClass(root, "error");
  assert.equal(errors.length, 4);
  for (const node of errors) {
    assert.ok(node.textContent.includes("definition read broke"));
  }
  mounted.unmount();
});
