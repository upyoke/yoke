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
  documentNode.defaultView.location.hash = "#/workflows?project=1";
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

test("Workflows renders the three panels from one served definition", async (t) => {
  const client = workflowsClient([
    {
      id: "demo-release", name: "Demo Release", target_env: "prod",
      status: "disabled", on_failure: "halt",
      stage_names: ["build", "verify"], project: "yoke",
    },
  ]);
  const { root, mounted } = await mountWorkflows(t, client);

  // One read, scoped to the picked project through the payload.
  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "workflows.definition.get",
    ),
    { function: "workflows.definition.get", payload: { project: "1" } },
  );
  assert.deepEqual(panelTitles(root), ["Types", "Gates", "Flows"]);

  // The single-scope picker: one radio chip per project, no All chip.
  const chips = byClass(root, "scope-chip");
  assert.deepEqual(chips.map((chip) => chip.textContent), ["Yoke"]);
  assert.ok(chips[0].classList.contains("on"));

  // The lifecycle half is universe-wide today, and the screen says so.
  const notes = byClass(root, "view-note");
  assert.equal(notes.length, 1);
  assert.ok(notes[0].textContent.includes("universe-wide"));

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
    // Flows: id | name | target env | status | joined stages | on failure.
    "demo-release", "Demo Release", "prod", "disabled", "build → verify", "halt",
  ]);

  // The flow id cell wears the identifier (mono) treatment.
  const monoCells = allNodes(root).filter(
    (node) => node.tagName === "TD" && node.classList.contains("mono"),
  );
  assert.deepEqual(monoCells.map(cellText), ["demo-release"]);
  mounted.unmount();
});

test("no declared flows renders the honest empty state", async (t) => {
  const client = workflowsClient([]);
  const { root, mounted } = await mountWorkflows(t, client);

  assert.deepEqual(panelTitles(root), ["Types", "Gates", "Flows"]);
  const text = allNodes(root)
    .map((node) => node.textContent || "").join(" ");
  assert.ok(text.includes("no deployment flows declared for this project"));
  // The lifecycle panels still fill: an empty flows table is a fact about
  // this project, not a failure of the read.
  assert.ok(text.includes("draft → review → ship"));
  mounted.unmount();
});

test("a failed read fails all three panels instead of sticking at loading", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/workflows?project=1";
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
  assert.equal(errors.length, 3);
  for (const node of errors) {
    assert.ok(node.textContent.includes("definition read broke"));
  }
  mounted.unmount();
});
