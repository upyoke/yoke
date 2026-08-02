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
  workflowFixture,
  workflowsClient,
} from "./universe_ui_workflows_test_support.mjs";

test("the editable path-survey default publishes a separate immutable version", async (t) => {
  const dash = workflowFixture({
    id: "dash",
    name: "Dash",
    currentVersion: 1,
    policies: {
      ownership: "exclusive_session_work_claim",
      file_budget: "optional",
      path_claims: "required",
      path_survey: "required",
      worktrees: "single_implementation_lane",
      parallelism: "none",
      generated_children: "none",
      qa: "optional_item_attachment",
      approvals: "none",
      delivery: "after_merge_action",
      item_posture_allowlist: ["path_survey"],
    },
  });
  const client = workflowsClient([dash]);
  const { root, mounted } = await mountWorkflows(t, client);

  const turnOff = allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Turn off",
  );
  assert.ok(turnOff);
  turnOff.dispatchEvent(new Event("click"));
  assert.deepEqual(classText(root, "workflow-dialog-title"), [
    "Turn off path survey",
  ]);
  assert.ok(allNodes(root).some(
    (node) => node.textContent.includes("declared-path fingerprint") &&
      node.textContent.includes("does not reserve those files"),
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
        path_survey_default: false,
      },
    },
  );
  assert.ok(classText(root, "workflow-posture-value").includes("off by default"));
  mounted.unmount();
});
