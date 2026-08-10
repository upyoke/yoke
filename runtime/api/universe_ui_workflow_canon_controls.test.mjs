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
  workflowFixture,
  workflowsClient,
} from "./universe_ui_workflows_test_support.mjs";

function canonWorkflow({
  id,
  name,
  currentVersion,
  state,
  follow,
  adoptedFrom = null,
}) {
  const workflow = workflowFixture({ id, name, currentVersion });
  workflow.source = "built_in";
  workflow.canon_status = {
    state,
    follow,
    adopted_from_version: adoptedFrom,
    latest_canon_version: 4,
  };
  return workflow;
}

test("canon follow, batch updates, and adoption history are operable", async (t) => {
  const workflows = [
    canonWorkflow({
      id: "dash",
      name: "Dash",
      currentVersion: 3,
      state: "update_available",
      follow: "manual",
      adoptedFrom: 2,
    }),
    canonWorkflow({
      id: "issue",
      name: "Issue",
      currentVersion: 2,
      state: "customized_update_available",
      follow: "manual",
    }),
    canonWorkflow({
      id: "epic",
      name: "Epic",
      currentVersion: 4,
      state: "up_to_date",
      follow: "auto",
    }),
  ];
  const client = workflowsClient(workflows);
  const callBase = client.call.bind(client);
  client.call = async (request) => {
    if (request.function === "workflows.canon_follow.set") {
      client.requests.push(request);
      return okEnvelope({
        workflow_id: request.payload.workflow_id,
        follow: request.payload.follow,
      });
    }
    if (request.function === "workflows.canon_update.apply_all") {
      client.requests.push(request);
      return okEnvelope({
        applied: [{ workflow_id: "dash", version: 4 }],
        refused: [{
          workflow_id: "issue",
          code: "incompatible",
          message: "local edits conflict",
        }],
      });
    }
    return callBase(request);
  };
  const { root, mounted } = await mountWorkflows(t, client);

  assert.deepEqual(classText(root, "workflow-canon-follow-state"), [
    "Yoke workflow updates: manual",
  ]);
  assert.deepEqual(classText(root, "workflow-canon-adoption-notice"), [
    "Updated automatically from Yoke version 2.",
  ]);
  allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Follow updates",
  ).dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "workflows.canon_follow.set",
    ),
    {
      function: "workflows.canon_follow.set",
      payload: { workflow_id: "dash", follow: "auto" },
    },
  );

  byClass(root, "workflow-canon-take-all")[0]
    .dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "workflows.canon_update.apply_all",
    ),
    {
      function: "workflows.canon_update.apply_all",
      payload: {
        workflows: [
          { workflow_id: "dash", expected_current_version: 3 },
          { workflow_id: "issue", expected_current_version: 2 },
        ],
      },
    },
  );
  assert.deepEqual(classText(root, "workflow-canon-batch-entry"), [
    "Dash — updated to v4.",
    "Issue — not updated: local edits conflict",
  ]);
  mounted.unmount();
});
