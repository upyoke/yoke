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

function dashFixture() {
  return workflowFixture({
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
      approval_defaults: {},
      delivery: "after_merge_action",
      item_posture_allowlist: [
        "verification", "path_claims", "approval_on_done", "deployment",
      ],
    },
  });
}

function mechanicsClient() {
  const base = workflowsClient([dashFixture()]);
  const callBase = base.call.bind(base);
  base.call = async (request) => {
    if (request.function === "workflows.definition.get") {
      const result = await callBase(request);
      result.envelope.result.flows = [{
        id: "yoke-production",
        name: "Yoke production",
        project: "yoke",
        status: "active",
      }];
      return result;
    }
    if (request.function === "workflows.mechanics.get") {
      base.requests.push(request);
      return okEnvelope({
        testing_defaults: [],
        delivery_defaults: [],
        approvers: [{ id: 2, label: "ben" }],
      });
    }
    if (request.function === "qa.plan.list") {
      base.requests.push(request);
      return okEnvelope({
        rows: [{
          id: 9,
          project: "yoke",
          slug: "release-readiness",
          name: "Release readiness",
          attachments: [],
        }],
      });
    }
    if (
      request.function === "workflows.testing_default.set" ||
      request.function === "workflows.delivery_default.set" ||
      request.function === "workflows.approval_defaults.publish"
    ) {
      base.requests.push(request);
      return okEnvelope({ result: { changed: true } });
    }
    return callBase(request);
  };
  return base;
}

function buttonByText(root, text) {
  return allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === text,
  );
}

test("approval editor publishes structured addressees as a new version", async (t) => {
  const client = mechanicsClient();
  const { root, mounted } = await mountWorkflows(t, client);

  buttonByText(root, "Set universe defaults for Dash")
    .dispatchEvent(new Event("click"));
  assert.deepEqual(classText(root, "workflow-dialog-title"), [
    "Default approvals — Dash",
  ]);
  assert.equal(byClass(root, "workflow-checkbox").length, 4);
  byClass(root, "workflow-checkbox")[0].children[0]
    .dispatchEvent(new Event("change"));
  buttonByText(root, "Save universe default")
    .dispatchEvent(new Event("click"));
  await settle();

  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "workflows.approval_defaults.publish",
    ),
    {
      function: "workflows.approval_defaults.publish",
      payload: {
        workflow_id: "dash",
        expected_current_version: 1,
        approval_defaults: {
          prove: { roles: ["owner"], actors: [] },
        },
      },
    },
  );
  mounted.unmount();
});

test("Testing and Delivery editors stay project-owned and can apply broadly", async (t) => {
  const client = mechanicsClient();
  const { root, mounted } = await mountWorkflows(t, client);

  buttonByText(root, "Edit Dash defaults for each project")
    .dispatchEvent(new Event("click"));
  assert.deepEqual(classText(root, "workflow-dialog-title"), [
    "Default test plan — Dash",
  ]);
  byClass(root, "workflow-checkbox")[0].children[0]
    .dispatchEvent(new Event("change"));
  buttonByText(root, "Set default").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "workflows.testing_default.set",
    ),
    {
      function: "workflows.testing_default.set",
      payload: {
        project: "yoke",
        workflow_id: "dash",
        plan_id: 9,
        apply_to_all: true,
      },
    },
  );

  const deliveryButtons = allNodes(root).filter(
    (node) => node.tagName === "BUTTON" &&
      node.textContent === "Edit Dash defaults for each project",
  );
  deliveryButtons[1].dispatchEvent(new Event("click"));
  assert.deepEqual(classText(root, "workflow-dialog-title"), [
    "Default deployment flow — Dash",
  ]);
  buttonByText(root, "Set default").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "workflows.delivery_default.set",
    ),
    {
      function: "workflows.delivery_default.set",
      payload: {
        project: "yoke",
        workflow_id: "dash",
        flow_id: "yoke-production",
        apply_to_all: false,
      },
    },
  );
  mounted.unmount();
});

test("a viewer without mechanics authority still sees the workflow", async (t) => {
  const client = workflowsClient([dashFixture()]);
  const callBase = client.call.bind(client);
  client.call = async (request) => {
    if (request.function === "workflows.mechanics.get") {
      client.requests.push(request);
      return {
        status: 200,
        envelope: {
          success: false,
          error: { message: "org admin required" },
        },
      };
    }
    return callBase(request);
  };
  const { root, mounted } = await mountWorkflows(t, client);

  assert.deepEqual(classText(root, "workflow-tab"), ["Dash"]);
  assert.ok(panelTitles(root).includes("Stages"));
  assert.equal(
    buttonByText(root, "Set universe defaults for Dash"),
    undefined,
  );
  assert.equal(
    buttonByText(root, "Edit Dash defaults for each project"),
    undefined,
  );
  assert.equal(buttonByText(root, "Turn on"), undefined);
  mounted.unmount();
});
