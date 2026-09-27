// A settled run keeps the exact evidence a person approved or rejected on
// both delivery views, including the review attached to a carried member.

import assert from "node:assert/strict";
import test from "node:test";

import { FakeDocument, byClass, settle } from "./universe_ui_dom_test_support.mjs";
import { shippingRunCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_work_cards.js";
import { loadCarriedItemEvidence } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_carried_item_evidence.js";
import { renderRunDetailView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_run_detail.js";

const RUN_ID = "run-review-evidence";
const MEMBER_SEQUENCE = 42;
const MEMBER_REF = `YOK-${MEMBER_SEQUENCE}`;
const artifact = (id) => ({ id, artifact_type: "screenshot", content_type: "image/png" });
const resolved = (requestId, kind, action, context) => ({
  request_id: requestId, kind, status: "resolved", subject_context: context,
  resolution_action: action, resolved_by: "Ben Bauman",
  resolved_at: "2026-09-27T06:00:00Z", actions: ["approve", "reject"],
  can_act: true,
});

function runRow(memberAction) {
  return {
    id: RUN_ID, project: "yoke", flow: "hosted-release", status: "executing",
    current_stage: "complete", target_environment: "prod",
    release_lineage: "candidate", created_at: "2026-09-27T05:00:00Z",
    stages: [{ name: "approval", state: "complete" }],
    member_items: [{
      id: MEMBER_SEQUENCE, ref: MEMBER_REF, title: "Member", project_id: 1,
      project_sequence: MEMBER_SEQUENCE,
    }],
    gates: [
      resolved(71, "deployment_stage_approval", "approve", {
        evidence: { screenshots: Array.from({ length: 8 },
          (_, index) => artifact(701 + index)) },
      }),
      resolved(72, "qa_needs_review", memberAction, {
        requirement_id: 901,
        subject: { kind: "deployment_run", deployment_run_id: RUN_ID,
          deployment_member_item_id: MEMBER_SEQUENCE },
        artifacts: [artifact(811), artifact(812)],
      }),
    ],
  };
}

function clientFor(row) {
  return {
    async call(request) {
      const result = (() => {
        if (request.function === "deployment_runs.list") {
          return { rows: [row], filters: { flows: [] } };
        }
        if (request.function === "qa.activity.list") return { rows: [] };
        if (request.function === "inbox.list") return { needs_decision: [] };
        if (request.function === "projects.infrastructure.list") {
          return { environments: [] };
        }
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

function assertDecisionEvidence(host, memberAction, memberClass) {
  const more = byClass(host, "review-more");
  assert.equal(more.length, 1);
  if (more[0].getAttribute("aria-expanded") !== "true") {
    more[0].dispatchEvent(new Event("click"));
  }
  assert.deepEqual(byClass(host, "review-shot").map(
    (node) => Number(node.getAttribute("data-artifact-id"))),
  [811, 812, 701, 702, 703, 704, 705, 706, 707, 708]);
  const member = byClass(host, memberClass)[0];
  assert.deepEqual(byClass(member, "review-shot").map(
    (node) => Number(node.getAttribute("data-artifact-id"))), [811, 812]);
  assert.equal(byClass(member, "review-action").length, 0);
  const records = byClass(host, "run-decision-record");
  assert.equal(records.length, 2);
  const memberRecord = records.find((node) => member.contains(node));
  const runRecord = records.find((node) => !member.contains(node));
  assert.ok(memberRecord.textContent.includes(
    `${memberAction === "approve" ? "Approved" : "Rejected"} by Ben Bauman`));
  assert.ok(runRecord.textContent.includes("Approved by Ben Bauman"));
  assert.equal(byClass(host, "review-action").length, 0);
  assert.equal(byClass(host, "review-question").length, 0);
  assert.equal(byClass(host, "review-card").length, 2);
}

for (const memberAction of ["approve", "reject"]) {
  const memberOutcome = memberAction === "approve" ? "approved" : "rejected";
  test(`Shipping retains an ${memberOutcome} member review and run approval`, async () => {
    const row = runRow(memberAction);
    const documentNode = new FakeDocument();
    const context = contextFor(documentNode, row);
    const itemFacts = await loadCarriedItemEvidence(context, row.member_items);
    const card = shippingRunCard(context, row, ["1"], { itemFacts });
    await settle();
    assertDecisionEvidence(card, memberAction, "release-member");
  });

  test(`run detail retains an ${memberOutcome} member review and run approval`, async () => {
    const row = runRow(memberAction);
    const documentNode = new FakeDocument();
    const context = contextFor(documentNode, row);
    const main = documentNode.createElement("main");
    await renderRunDetailView(context, main, ["1"], RUN_ID);
    await settle();
    assertDecisionEvidence(main, memberAction, "run-items");
  });
}
