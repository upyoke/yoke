import assert from "node:assert/strict";
import test from "node:test";

import {
  mountUniverseApp,
} from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
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

function workflowFixture({
  id = "rally",
  name = "Rally",
  description = "Coordinate a small release train.",
  stages,
  currentVersion = 3,
  versions,
} = {}) {
  return {
    id,
    name,
    description,
    source: "pack",
    status: "disabled",
    current_version: currentVersion,
    published_at: "2026-07-25T12:00:00Z",
    versions: versions || [
      {
        version: 1,
        definition_digest: `${id}-first`,
        published_at: "2026-07-20T12:00:00Z",
      },
      {
        version: currentVersion,
        definition_digest: `${id}-current`,
        published_at: "2026-07-25T12:00:00Z",
      },
    ],
    definition: {
      stages: stages || [
        { id: "draft", label: "Drafted", gates: [] },
        {
          id: "prove",
          label: "Proving",
          gates: [{ id: "evidence_check", mode: "strict" }],
          description: "Collect the declared proof.",
        },
        { id: "ship", label: "Shipped", gates: [] },
      ],
      entry_surfaces: ["cli", "harness_skill"],
      executor_bindings: [
        {
          executor_id: "advance",
          from_stage_id: "draft",
          through_stage_id: "ship",
        },
      ],
      policies: {
        ownership: "single_item_claim",
        path_claims: "required",
        worktrees: "single_implementation_lane",
        parallelism: "inside_item",
        generated_children: "none",
        qa: "project_transition_defaults",
        approvals: "definition_transitions",
        delivery: "release_stage",
        item_posture_allowlist: ["verification"],
      },
    },
  };
}

function definitionFixture(workflows = [workflowFixture()]) {
  return {
    family: "work-items",
    workflows,
    gate_catalog: [{
      id: "evidence_check",
      name: "Evidence check",
      source_kind: "status_gate",
      availability: "live",
      description: "The declared proof must exist.",
    }],
    flows: [],
  };
}

function workflowsClient(workflows) {
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
        return okEnvelope(definitionFixture(workflows));
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

function classText(root, className) {
  return byClass(root, className).map((node) => node.textContent);
}

test("Workflows renders the registry as the lifecycle experience", async (t) => {
  const client = workflowsClient();
  const { root, mounted } = await mountWorkflows(t, client);

  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "workflows.definition.get",
    ),
    { function: "workflows.definition.get", payload: {} },
  );
  assert.deepEqual(
    panelTitles(root),
    ["Stages", "Execution posture", "Mechanics", "Version history"],
  );
  assert.deepEqual(classText(root, "workflow-tab"), ["Rally"]);
  assert.deepEqual(classText(root, "workflow-stage-label"), [
    "Drafted", "Proving", "Shipped",
  ]);
  assert.deepEqual(classText(root, "workflow-stage-count"), [
    "entry", "1 check",
  ]);
  assert.deepEqual(classText(root, "workflow-detail-row-title"), [
    "CLI", "Harness", "Executor", "Testing", "Approvals", "Delivery",
  ]);
  assert.deepEqual(classText(root, "workflow-posture-value"), [
    "one active item claim",
    "required from file budget",
    "one implementation lane",
    "inside the item only",
    "governed migrations on every change",
  ]);
  assert.deepEqual(classText(root, "workflow-version-title"), [
    "v3 · current", "v1",
  ]);

  assert.equal(
    allNodes(root).filter((node) => node.tagName === "TABLE").length,
    0,
  );
  assert.equal(byClass(root, "raw-toggle").length, 0);
  assert.equal(byClass(root, "scope-bar").length, 0);
  mounted.unmount();
});

test("selecting a stage opens its served description and gate cards", async (t) => {
  const { root, mounted } = await mountWorkflows(t, workflowsClient());
  const proving = byClass(root, "workflow-stage")[1];
  proving.dispatchEvent(new Event("click"));

  assert.deepEqual(
    classText(root, "workflow-stage-description"),
    ["Collect the declared proof."],
  );
  assert.deepEqual(classText(root, "workflow-detail-row-title").slice(0, 1), [
    "Evidence check — strict",
  ]);
  assert.deepEqual(classText(root, "workflow-detail-row-description").slice(0, 1), [
    "The declared proof must exist.",
  ]);
  assert.deepEqual(classText(root, "workflow-detail-id").slice(0, 1), [
    "evidence_check",
  ]);
  assert.equal(byClass(root, "workflow-stage")[1].attributes.get("aria-pressed"), "true");
  mounted.unmount();
});

test("workflow tabs use the decided built-in order and open Dash first", async (t) => {
  const workflows = [
    workflowFixture({ id: "epic", name: "Epic", currentVersion: 1 }),
    workflowFixture({ id: "issue", name: "Issue", currentVersion: 1 }),
    workflowFixture({ id: "blitz", name: "Blitz", currentVersion: 1 }),
    workflowFixture({
      id: "dash",
      name: "Dash",
      description: "A short instruction filed in seconds.",
      currentVersion: 1,
    }),
    workflowFixture({ id: "rally", name: "Rally", currentVersion: 1 }),
  ];
  const { root, mounted } = await mountWorkflows(
    t, workflowsClient(workflows),
  );

  assert.deepEqual(classText(root, "workflow-tab"), [
    "Dash", "Blitz", "Issue", "Epic", "Rally",
  ]);
  assert.equal(byClass(root, "workflow-tab")[0].attributes.get("aria-selected"), "true");
  assert.deepEqual(classText(root, "workflow-intro"), [
    "A short instruction filed in seconds.",
  ]);

  byClass(root, "workflow-tab")[2].dispatchEvent(new Event("click"));
  assert.equal(byClass(root, "workflow-tab")[2].attributes.get("aria-selected"), "true");
  assert.deepEqual(classText(root, "workflow-intro"), [
    "Coordinate a small release train.",
  ]);
  mounted.unmount();
});

test("version history inspection reveals the immutable digest", async (t) => {
  const { root, mounted } = await mountWorkflows(t, workflowsClient());
  byClass(root, "workflow-button")[0].dispatchEvent(new Event("click"));
  assert.deepEqual(classText(root, "workflow-version-inspection"), [
    "rally-first",
  ]);
  byClass(root, "workflow-button")[0].dispatchEvent(new Event("click"));
  assert.deepEqual(classText(root, "workflow-version-inspection"), []);
  mounted.unmount();
});

test("a failed registry read renders one honest screen failure", async (t) => {
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
  const { root, mounted } = await mountWorkflows(t, client);
  const errors = byClass(root, "error");
  assert.equal(errors.length, 1);
  assert.ok(errors[0].textContent.includes("definition read broke"));
  mounted.unmount();
});
