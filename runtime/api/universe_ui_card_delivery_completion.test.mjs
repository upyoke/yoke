import assert from "node:assert/strict";
import test from "node:test";

import {
  appendItemDelivery, deliverySummary, deploymentsByItemId,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_item_deployment.js";
import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";

// A member whose QA is clear reads its QA disposition and, separately, where
// its completion stands — from its own done approval's standing, never from
// the approval's mere existence.
const ITEM_ID = 470;
const ITEM_REF = "YOK-70";
const NO_QA = { state: "discharged", no_item_qa_required: true };

function approval(standing, facts = {}) {
  return {
    request_id: 12, kind: "lifecycle_transition_approval", standing,
    status: standing === "pending" ? "pending" : "resolved",
    subject_context: { item_id: ITEM_ID, item_ref: ITEM_REF, to_stage: "done" },
    ...facts,
  };
}

function outcome(gates, runFacts = {}, qa = NO_QA) {
  const documentNode = new FakeDocument();
  const box = appendItemDelivery(documentNode, documentNode.createElement("div"), {
    public_ref: ITEM_REF, project_id: 1, completion_flow: "flow",
  }, deploymentsByItemId([{
    id: "run-member", status: "executing", target_environment: "prod",
    current_stage: "item-qa", created_at: new Date().toISOString(), gates,
    member_items: [{ id: ITEM_ID, ref: ITEM_REF, status: "release", item_qa: qa }],
    ...runFacts,
  }]));
  return byClass(box, "item-deployment-outcome")[0];
}

test("a pending done approval reads awaiting approval beside the QA disposition", () => {
  assert.equal(outcome([approval("pending")]).textContent, "◐ no item QA required · awaiting approval");
});

test("an approved member still open says completion is pending and where to look", () => {
  const node = outcome([approval("approved")]);
  assert.equal(node.textContent, "◐ no item QA required · approved · completion pending");
  assert.match(node.title, /yoke items get YOK-70 status/);
});

test("closing needs the run's active settlement, not the approval alone", () => {
  const node = outcome([approval("approved")], { settling_at: new Date().toISOString() });
  assert.equal(node.textContent, "◐ no item QA required · approved · closing");
});

test("a rejected done approval reads rejected, never awaiting completion", () => {
  assert.equal(outcome([approval("rejected")], {}, { state: "accepted" }).textContent,
    "✗ QA passed · approval rejected");
});

test("a superseded approval or a sibling's approval does not speak for this member", () => {
  const sibling = approval("pending", {
    request_id: 13, subject_context: { item_id: ITEM_ID + 1, to_stage: "done" },
  });
  assert.equal(outcome([approval("superseded"), sibling]).textContent,
    "◐ no item QA required · awaiting item completion");
});

test("the newest of the member's approvals is the one shown", () => {
  const older = approval("rejected", { request_id: 4 });
  assert.equal(outcome([older, approval("pending")]).textContent,
    "◐ no item QA required · awaiting approval");
});

const COMPLETED = [{ environment: "prod", run_id: "run-prod", run_project_id: 1 }];

function completedCard({ qa, status = "succeeded", itemStatus = "done", memberStatus = "release",
  completed = COMPLETED, relation = "member" } = {}) {
  const documentNode = new FakeDocument();
  const row = { public_ref: ITEM_REF, status: itemStatus, delivery: { completed_deliveries: completed } };
  const member = { id: ITEM_ID, ref: ITEM_REF, status: memberStatus, item_qa: qa };
  const deployments = deploymentsByItemId([{
    id: "run-stage", status, target_environment: "stage",
    [relation === "removed" ? "removed_member_items" : "member_items"]: [member],
  }]);
  const box = appendItemDelivery(documentNode, documentNode.createElement("div"), row, deployments);
  return { lines: byClass(box, "item-deployment-outcome").map((node) => node.textContent),
    summary: deliverySummary(row, deployments) };
}

test("done cards keep waived QA beside the actual completion environment", () => {
  const result = completedCard({ qa: { state: "discharged" } });
  assert.deepEqual(result.lines, ["◐ QA waived · item completed in prod", "✓ deployed · item completed"]);
  assert.equal(result.summary, "✓ Live in stage · ✓ Live in prod");
});

test("a succeeded member with QA still pending reads the item's completion", () => {
  const result = completedCard({ qa: { state: "not yet run" } });
  assert.deepEqual(result.lines, ["○ item completed in prod", "✓ deployed · item completed"]);
  assert.equal(result.summary, "✓ Live in stage · ✓ Live in prod");
});

test("member status supplies done when row status is absent, without inventing an environment", () => {
  const result = completedCard({ qa: { state: "accepted" }, itemStatus: null,
    memberStatus: "done", completed: [] });
  assert.deepEqual(result.lines, ["◐ QA passed · item completed"]);
  assert.equal(result.summary, "✓ Live in stage");
});

test("a done item's executing cleared member is not yet live", () => {
  const result = completedCard({ qa: NO_QA, status: "executing" });
  assert.equal(result.lines[0], "◐ no item QA required · item completed in prod");
  assert.equal(result.summary, "Deploying to stage · ✓ Live in prod");
});

test("not-done members, failed QA and removed rows keep their outcomes", () => {
  assert.equal(completedCard({ itemStatus: "release", qa: NO_QA }).lines[0],
    "◐ no item QA required · awaiting item completion");
  assert.equal(completedCard({ itemStatus: "release" }).lines[0], "○ awaiting item completion");
  assert.equal(completedCard({ qa: { state: "rejected" } }).lines[0], "✗ QA failed");
  assert.equal(completedCard({ qa: { failed_requirement_ids: [42] } }).lines[0], "✗ QA failed · #42");
  assert.equal(completedCard({ relation: "removed" }).lines[0], "○ removed · rides a later release");
});
