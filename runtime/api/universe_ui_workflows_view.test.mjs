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

// A served definition with invented vocabulary: nothing here matches the
// engine's real status or gate names, so anything the view shows beyond
// these strings would be hardcoded — the assertion the fixture exists for.
// The same read also serves deployment flows, which this screen deliberately
// does not show — they are Delivery's Flows facet.
function definitionFixture(flows) {
  return {
    family: "software-delivery",
    types: [
      {
        type: "issue",
        stages: ["draft", "review", "ship"],
        gates: [{ at_status: "review", gate: "evidence_check" }],
      },
      {
        type: "epic",
        stages: ["draft", "plan", "review", "ship"],
        gates: [
          { at_status: "review", gate: "evidence_check" },
          { at_status: "plan", gate: "plan_walkthrough" },
        ],
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

test("Workflows renders the lifecycle definition from one served read", async (t) => {
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
  assert.deepEqual(panelTitles(root), ["Types", "Gates"]);

  // Nothing on this screen takes a project, so it draws no picker — and no
  // note explaining a picker that is not there.
  assert.equal(byClass(root, "scope-bar").length, 0);
  assert.equal(byClass(root, "scope-chip").length, 0);
  assert.equal(byClass(root, "view-note").length, 0);

  const cells = allNodes(root)
    .filter((node) => node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells, [
    // Types: type | stage count | the full served progression, verbatim.
    "issue", "3", "draft → review → ship",
    "epic", "4", "draft → plan → review → ship",
    // Gates: each served (status, gate) fact once, ordered by the longest
    // served progression — plan precedes review because the epic fixture
    // says so, not because this module knows either word.
    "plan", "plan_walkthrough",
    "review", "evidence_check",
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

test("a failed read fails both panels instead of sticking at loading", async (t) => {
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
  assert.equal(errors.length, 2);
  for (const node of errors) {
    assert.ok(node.textContent.includes("definition read broke"));
  }
  mounted.unmount();
});
