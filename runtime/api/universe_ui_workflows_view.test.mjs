import assert from "node:assert/strict";
import test from "node:test";

import {
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  classText,
  mountWorkflows,
  okEnvelope,
  panelTitles,
  workflowFixture,
  workflowsClient,
} from "./universe_ui_workflows_test_support.mjs";

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

test("version inspection reads the immutable definition and can select it", async (t) => {
  const client = workflowsClient();
  const { root, mounted } = await mountWorkflows(t, client);
  byClass(root, "workflow-button")[0].dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(classText(root, "workflow-version-digest"), [
    "rally-first",
  ]);
  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "workflows.version.get",
    ),
    {
      function: "workflows.version.get",
      payload: { workflow_id: "rally", version: 1 },
    },
  );

  allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Make current",
  ).dispatchEvent(new Event("click"));
  assert.deepEqual(classText(root, "workflow-dialog-title"), [
    "Make Rally v1 current?",
  ]);
  byClass(root, "primary")[0].dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "workflows.current.set",
    ),
    {
      function: "workflows.current.set",
      payload: {
        workflow_id: "rally",
        version: 1,
        expected_current_version: 3,
      },
    },
  );
  assert.deepEqual(classText(root, "workflow-version-title"), [
    "v3", "v1 · current",
  ]);
  mounted.unmount();
});

test("the editable path-claims default publishes a new immutable version", async (t) => {
  const dash = workflowFixture({
    id: "dash",
    name: "Dash",
    currentVersion: 1,
    policies: {
      ownership: "exclusive_session_work_claim",
      path_claims: "optional",
      worktrees: "single_implementation_lane",
      parallelism: "none",
      generated_children: "none",
      qa: "optional_item_attachment",
      approvals: "none",
      delivery: "after_merge_action",
      item_posture_allowlist: [
        "verification", "path_claims", "approval_on_done", "deployment",
      ],
    },
  });
  const client = workflowsClient([dash]);
  const { root, mounted } = await mountWorkflows(t, client);

  const turnOn = allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Turn on",
  );
  assert.ok(turnOn);
  turnOn.dispatchEvent(new Event("click"));
  assert.deepEqual(classText(root, "workflow-dialog-title"), [
    "Turn on path claims",
  ]);
  assert.ok(classText(root, "workflow-dialog-impact")[0].includes(
    "Publishing creates Dash v2",
  ));
  byClass(root, "primary")[0].dispatchEvent(new Event("click"));
  await settle();

  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "workflows.policy_defaults.publish",
    ),
    {
      function: "workflows.policy_defaults.publish",
      payload: {
        workflow_id: "dash",
        expected_current_version: 1,
        path_claims_default: true,
      },
    },
  );
  assert.ok(classText(root, "workflow-posture-value").includes("on by default"));
  assert.deepEqual(classText(root, "workflow-version-title"), [
    "v2 · current", "v1",
  ]);
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
