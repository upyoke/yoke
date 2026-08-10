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

function editableDash() {
  return workflowFixture({
    id: "dash",
    name: "Dash",
    currentVersion: 1,
    skillBindings: [{
      skill_id: "dash",
      from_stage_id: "draft",
      through_stage_id: "ship",
    }],
    policies: {
      ownership: "exclusive_session_work_claim",
      file_budget: "optional",
      path_claims: "optional",
      path_survey: "required",
      worktrees: "single_implementation_lane",
      generated_children: "none",
      qa: "optional_item_attachment",
      approvals: "none",
      delivery: "after_merge_action",
      item_posture_allowlist: [
        "verification", "path_claims", "path_survey",
      ],
    },
  });
}

test("one coordination control offers the three exclusive approved levels", async (t) => {
  const client = workflowsClient([editableDash()]);
  const { root, mounted } = await mountWorkflows(t, client);

  assert.deepEqual(
    classText(root, "workflow-posture-name").filter(
      (name) => name.includes("Path") || name.includes("overlapping"),
    ),
    ["Preventing overlapping work"],
  );
  assert.equal(byClass(root, "workflow-coordination-tag").length, 0);
  allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Change",
  ).dispatchEvent(new Event("click"));

  assert.deepEqual(classText(root, "workflow-dialog-title"), [
    "Preventing overlapping work",
  ]);
  assert.deepEqual(classText(root, "workflow-coordination-name"), [
    "No prevention", "Path survey", "Path claims",
  ]);
  assert.deepEqual(classText(root, "workflow-coordination-tag"), [
    "fastest", "faster", "safest",
  ]);
  const dialog = byClass(root, "workflow-dialog")[0];
  assert.equal(
    byClass(dialog, "workflow-coordination-tag").length,
    byClass(root, "workflow-coordination-tag").length,
  );
  const options = byClass(root, "workflow-coordination-option");
  options[2].dispatchEvent(new Event("click"));
  assert.deepEqual(
    options.map((option) => option.attributes.get("aria-checked")),
    ["false", "false", "true"],
  );
  byClass(root, "primary")[0].dispatchEvent(new Event("click"));
  await settle();

  assert.deepEqual(
    client.requests.filter(
      (request) => request.function === "workflows.policy_defaults.publish",
    ),
    [
      {
        function: "workflows.policy_defaults.publish",
        payload: {
          workflow_id: "dash",
          expected_current_version: 1,
          path_survey_default: false,
        },
      },
      {
        function: "workflows.policy_defaults.publish",
        payload: {
          workflow_id: "dash",
          expected_current_version: 2,
          path_claims_default: true,
        },
      },
    ],
  );
  assert.ok(classText(root, "workflow-posture-value").includes("Path claims"));
  assert.ok(classText(root, "workflow-posture-value").includes(
    "one implementation lane",
  ));
  assert.ok(classText(root, "workflow-detail-row-description").includes(
    "Run /yoke dash in a supported harness like Claude Code or Codex — " +
    "it runs the whole item: survey, worktree, execute, verify, merge, evidence.",
  ));
  assert.deepEqual(classText(root, "workflow-version-title"), [
    "v3 · current", "v2", "v1",
  ]);
  assert.equal(
    classText(root, "workflow-version-description")[0],
    "edited here",
  );
  const publishedVersion = await client.call({
    function: "workflows.version.get",
    payload: { workflow_id: "dash", version: 3 },
  });
  assert.equal(publishedVersion.envelope.result.published_by_actor_id, 1);
  mounted.unmount();
});

test("a failed coordination publication restores the shared dialog", async (t) => {
  const client = workflowsClient([editableDash()]);
  const callBase = client.call.bind(client);
  client.call = async (request) => {
    if (request.function === "workflows.policy_defaults.publish") {
      throw new Error("publish unavailable");
    }
    return callBase(request);
  };
  const { root, mounted } = await mountWorkflows(t, client);

  allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Change",
  ).dispatchEvent(new Event("click"));
  byClass(root, "workflow-coordination-option")[2]
    .dispatchEvent(new Event("click"));
  const confirm = byClass(root, "primary")[0];
  confirm.dispatchEvent(new Event("click"));
  await settle();

  assert.equal(confirm.disabled, false);
  assert.equal(confirm.textContent, "Save coordination default");
  assert.deepEqual(classText(root, "workflow-dialog-error"), [
    "publish unavailable",
  ]);
  mounted.unmount();
});
