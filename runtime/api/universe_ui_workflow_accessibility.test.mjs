import assert from "node:assert/strict";
import test from "node:test";

import {
  allNodes,
  byClass,
  FakeDocument,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  mountWorkflows,
  workflowFixture,
  workflowsClient,
} from "./universe_ui_workflows_test_support.mjs";
import {
  renderTabs,
} from "../../packages/yoke-core/src/yoke_core/ui/static/workflow_view_primitives.js";

function keyEvent(key, options = {}) {
  const event = new Event("keydown");
  Object.defineProperties(event, {
    key: { value: key },
    shiftKey: { value: Boolean(options.shiftKey) },
  });
  return event;
}

test("workflow tabs implement roving keyboard selection", async () => {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("div");
  const workflows = [
    workflowFixture({ id: "dash", name: "Dash", currentVersion: 1 }),
    workflowFixture({ id: "blitz", name: "Blitz", currentVersion: 1 }),
    workflowFixture({ id: "issue", name: "Issue", currentVersion: 1 }),
  ];
  let selected = "dash";
  const render = () => renderTabs(
    documentNode,
    host,
    workflows,
    selected,
    (workflowId) => {
      selected = workflowId;
      render();
    },
  );
  render();

  assert.deepEqual(host.children.map((tab) => tab.tabIndex), [0, -1, -1]);
  host.children[0].focus();
  host.children[0].dispatchEvent(keyEvent("ArrowRight"));
  await Promise.resolve();

  assert.equal(selected, "blitz");
  assert.equal(documentNode.activeElement.textContent, "Blitz");
  assert.deepEqual(host.children.map((tab) => tab.tabIndex), [-1, 0, -1]);

  documentNode.activeElement.dispatchEvent(keyEvent("End"));
  await Promise.resolve();
  assert.equal(selected, "issue");
  assert.equal(documentNode.activeElement.textContent, "Issue");
});

test("workflow mutation dialogs trap focus and restore their opener", async (t) => {
  const dash = workflowFixture({
    id: "dash",
    name: "Dash",
    currentVersion: 1,
    policies: {
      ownership: "exclusive_session_work_claim",
      file_budget: "optional",
      path_claims: "optional",
      worktrees: "single_implementation_lane",
      generated_children: "none",
      qa: "optional_item_attachment",
      approvals: "none",
      delivery: "after_merge_action",
      item_posture_allowlist: ["path_claims"],
    },
  });
  const client = workflowsClient([dash]);
  const callBase = client.call.bind(client);
  client.call = async (request) => {
    if (request.function === "workflows.policy_defaults.publish") {
      throw new Error("publish unavailable");
    }
    return callBase(request);
  };
  const { documentNode, root, mounted } = await mountWorkflows(t, client);
  const trigger = allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Turn on",
  );
  trigger.focus();
  trigger.dispatchEvent(new Event("click"));

  const cancel = allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Cancel",
  );
  const confirm = byClass(root, "primary")[0];
  assert.equal(documentNode.activeElement, cancel);
  documentNode.defaultView.dispatchEvent(keyEvent("Tab"));
  assert.equal(documentNode.activeElement, confirm);
  documentNode.defaultView.dispatchEvent(keyEvent("Tab"));
  assert.equal(documentNode.activeElement, cancel);
  documentNode.defaultView.dispatchEvent(keyEvent("Tab", { shiftKey: true }));
  assert.equal(documentNode.activeElement, confirm);

  confirm.dispatchEvent(new Event("click"));
  documentNode.defaultView.dispatchEvent(keyEvent("Escape"));
  assert.equal(byClass(root, "workflow-dialog").length, 1);
  await settle();
  documentNode.defaultView.dispatchEvent(keyEvent("Escape"));
  assert.equal(byClass(root, "workflow-dialog").length, 0);
  assert.equal(documentNode.activeElement, trigger);
  mounted.unmount();
});
