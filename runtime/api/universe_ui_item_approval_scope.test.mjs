// A carried item's lifecycle approval belongs to the item, not the run.
//
// Shipping and run detail draw each carried item's "Item QA" and the run's
// own "Run QA" with the same components. An item's approval — pending with
// its controls, or answered with its record — sits once under that item
// beside the item's checks, never under Run QA; the run's own release
// approval stays under Run QA. A screenshot a check already drew is not
// drawn again by the decision, and an approval with no screenshot says so.

import assert from "node:assert/strict";
import test from "node:test";

import { FakeDocument, byClass, settle } from "./universe_ui_dom_test_support.mjs";
import { shippingRunCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_work_cards.js";
import { loadCarriedItemEvidence } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_carried_item_evidence.js";
import { renderRunDetailView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_run_detail.js";

const RUN_ID = "run-item-approval-scope";
const MEMBER_ID = 3609;
const MEMBER_REF = "YOK-156";
const image = (id) => ({ id, artifact_type: "screenshot", content_type: "image/png" });

function itemApproval(status, screenshots) {
  return {
    request_id: 9274, kind: "lifecycle_transition_approval", status,
    item_status: "release",
    subject_context: {
      item_id: MEMBER_ID, item_ref: MEMBER_REF, from_stage: "release", to_stage: "done",
      evidence: {
        state: screenshots.length ? "attached" : "missing",
        screenshots: screenshots.map((id) => ({ artifact_id: id,
          artifact_type: "screenshot", content_type: "image/png", requirement_id: 32969 })),
      },
    },
    actions: status === "pending" ? ["approve", "reject"] : [],
    can_act: status === "pending",
    resolution_action: status === "resolved" ? "approve" : null,
    resolved_by: "Ben Bauman", resolved_at: "2026-09-28T19:00:00Z",
  };
}

function runApproval() {
  return {
    request_id: 9300, kind: "deployment_stage_approval", status: "pending",
    subject_context: { evidence: { state: "absent", screenshots: [] } },
    actions: ["approve", "reject"], can_act: true,
  };
}

function runRow(approval) {
  return {
    id: RUN_ID, project: "yoke", flow: "hosted-release", status: "executing",
    current_stage: "approval", target_environment: "prod",
    release_lineage: "candidate", created_at: "2026-09-28T18:00:00Z",
    stages: [{ name: "approval", state: "running" }],
    member_items: [{ id: MEMBER_ID, ref: MEMBER_REF, title: "Member", project_id: 1,
      project_sequence: 156 }],
    gates: [approval, runApproval()],
  };
}

// The member's production QA: a capture this run recorded for the member.
const memberCheck = {
  requirement_id: 32969, deployment_run_id: RUN_ID, deployment_member_item_id: MEMBER_ID,
  item_id: null, project: "yoke", method_name: "Browser inspection", outcome: "passed",
  qa_phase: "post_deploy", happened_at: "2026-09-28T18:30:00Z", artifacts: [image(23626)],
};

function clientFor(row) {
  return {
    async call(request) {
      const result = (() => {
        if (request.function === "deployment_runs.list") {
          return { rows: [row], filters: { flows: [] } };
        }
        if (request.function === "qa.activity.list") {
          return { rows: request.payload.item_ids ? [memberCheck] : [] };
        }
        if (request.function === "inbox.list") return { needs_decision: [] };
        if (request.function === "projects.infrastructure.list") return { environments: [] };
        if (request.function === "deployment_runs.find_by_item") return { rows: [] };
        if (request.function === "qa.artifact.read") {
          return { disposition: "ready", content_type: "image/png",
            content_base64: "aVZCT1J3MEs=" };
        }
        throw new Error(`unexpected function ${request.function}`);
      })();
      return { status: 200, envelope: { success: true, result } };
    },
  };
}

function contextFor(documentNode, row) {
  return {
    document: documentNode, client: clientFor(row), isMounted: () => true,
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }],
  };
}

async function shipping(row) {
  const documentNode = new FakeDocument();
  const context = contextFor(documentNode, row);
  const itemFacts = await loadCarriedItemEvidence(context, row.member_items);
  const answered = [];
  const card = shippingRunCard(context, row, ["1"], {
    itemFacts, onGateAction: () => {},
    onItemDecision: (request, action) => answered.push([request.id, action]),
  });
  await settle();
  card.answered = answered;
  return card;
}

async function runDetail(row) {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  await renderRunDetailView(contextFor(documentNode, row), main, ["1"], RUN_ID);
  await settle();
  return main;
}

const requestIds = (node) => byClass(node, "run-request").map(
  (request) => request.getAttribute("data-request-id"));
const shotIds = (node) => byClass(node, "review-shot").map(
  (shot) => Number(shot.getAttribute("data-artifact-id")));

function runQa(host) {
  return byClass(host, "run-qa-section").find(
    (section) => !section.classList.contains("item-qa-section"));
}

for (const [view, render] of [["Shipping", shipping], ["run detail", runDetail]]) {
  for (const status of ["pending", "resolved"]) {
    test(`${view}: a ${status} item approval sits once under its item, not Run QA`, async () => {
      const host = await render(runRow(itemApproval(status, [23626])));
      const item = byClass(host, "item-qa-section")[0];
      assert.ok(item, "the carried item draws its Item QA");
      assert.equal(byClass(item, "run-qa-head")[0].children[0].textContent, "Item QA");
      assert.deepEqual(requestIds(item), ["9274"]);
      assert.deepEqual(requestIds(runQa(host)), ["9300"]);
      assert.equal(requestIds(host).filter((id) => id === "9274").length, 1);
      // The member's capture is its check's; the approval does not repeat it.
      assert.deepEqual(shotIds(item), [23626]);
      assert.equal(byClass(item, "run-qa-check-outcome")[0].textContent, "Passed");
      if (status === "pending") {
        assert.equal(byClass(item, "run-verdict")[0].textContent, "Awaiting approval");
        const approve = byClass(item, "review-action").find(
          (button) => button.getAttribute("data-action") === "approve");
        assert.ok(approve, "the pending approval is answered under its item");
        if (host.answered) {
          approve.dispatchEvent(new Event("click"));
          assert.deepEqual(host.answered, [[9274, "approve"]]);
        }
      } else {
        assert.equal(byClass(item, "review-action").length, 0);
        assert.match(byClass(item, "run-decision-record")[0].textContent,
          /^Approved by Ben Bauman/);
        // The check keeps its own result; "Approved" is the person's record.
        assert.equal(byClass(item, "run-verdict")[0].textContent, "1 of 1 passed");
      }
    });
  }

  test(`${view}: an item approval with no screenshot says so`, async () => {
    const row = runRow(itemApproval("pending", []));
    const host = await render({ ...row, member_items: row.member_items });
    const item = byClass(host, "item-qa-section")[0];
    const note = byClass(item, "review-evidence-note")[0];
    assert.equal(note.textContent,
      "QA ran for this decision's subject but captured no screenshot.");
  });
}
