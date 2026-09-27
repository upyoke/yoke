// A settled run keeps the exact evidence a person approved or rejected on
// both delivery views, including the review attached to a carried member.

import assert from "node:assert/strict";
import test from "node:test";

import { FakeDocument, byClass, settle } from "./universe_ui_dom_test_support.mjs";
import { shippingRunCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_work_cards.js";
import { loadCarriedItemEvidence } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_carried_item_evidence.js";
import { renderRunDetailView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_run_detail.js";

const RUN_ID = "run-review-evidence";
const artifact = (id) => ({ id, artifact_type: "screenshot", content_type: "image/png" });
const resolved = (requestId, kind, action, context) => ({
  request_id: requestId, kind, status: "resolved", subject_context: context,
  resolution_action: action, resolved_by: "Ben Bauman",
  resolved_at: "2026-09-27T06:00:00Z", actions: ["approve", "reject"],
  can_act: true,
});

function runRow() {
  return {
    id: RUN_ID, project: "yoke", flow: "hosted-release", status: "executing",
    current_stage: "complete", target_environment: "prod",
    release_lineage: "candidate", created_at: "2026-09-27T05:00:00Z",
    stages: [{ name: "approval", state: "complete" }],
    member_items: [{
      id: 42, ref: "YOK-42", title: "Member", project_id: 1,
      project_sequence: 42,
    }],
    gates: [
      resolved(71, "deployment_stage_approval", "approve", {
        evidence: { screenshots: Array.from({ length: 8 },
          (_, index) => artifact(701 + index)) },
      }),
      resolved(72, "qa_needs_review", "reject", {
        requirement_id: 901,
        subject: { kind: "deployment_run", deployment_run_id: RUN_ID,
          deployment_member_item_id: 42 },
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

function assertDecisionEvidence(host) {
  const more = byClass(host, "review-more");
  assert.equal(more.length, 1);
  more[0].dispatchEvent(new Event("click"));
  assert.deepEqual(byClass(host, "review-shot").map(
    (node) => Number(node.getAttribute("data-artifact-id"))),
  [811, 812, 701, 702, 703, 704, 705, 706, 707, 708]);
  const records = byClass(host, "run-decision-record").map((node) => node.textContent);
  assert.equal(records.length, 2);
  assert.ok(records.some((value) => value.includes("Approved by Ben Bauman")));
  assert.ok(records.some((value) => value.includes("Rejected by Ben Bauman")));
  assert.equal(byClass(host, "review-action").length, 0);
  assert.equal(byClass(host, "review-question").length, 0);
  assert.equal(byClass(host, "review-card").length, 2);
}

test("Shipping retains the reviewed run and member screenshots after resolution", async () => {
  const row = runRow();
  const documentNode = new FakeDocument();
  const context = contextFor(documentNode, row);
  const itemFacts = await loadCarriedItemEvidence(context, row.member_items);
  const card = shippingRunCard(context, row, ["1"], { itemFacts });
  await settle();
  assertDecisionEvidence(card);
  assert.equal(byClass(byClass(card, "release-member")[0], "review-shot").length, 2);
});

test("run detail retains the same frozen decisions and screenshots", async () => {
  const row = runRow();
  const documentNode = new FakeDocument();
  const context = contextFor(documentNode, row);
  const main = documentNode.createElement("main");
  await renderRunDetailView(context, main, ["1"], RUN_ID);
  await settle();
  assertDecisionEvidence(main);
  assert.equal(byClass(byClass(main, "run-items")[0], "review-shot").length, 2);
});
