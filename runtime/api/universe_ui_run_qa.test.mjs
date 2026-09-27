import assert from "node:assert/strict";
import test from "node:test";

import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";
import { shippingRunCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_work_cards.js";
import { effectiveRunChecks } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_run_evidence.js";

const runId = "run-current-qa";
const image = (id) => ({ id, artifact_type: "screenshot", content_type: "image/png" });
const checks = [
  { requirement_id: 8, deployment_run_id: runId, case_key: "Visual review",
    method_name: "Browser", outcome: "failed", happened_at: "2026-09-01T10:00:00Z",
    artifacts: [image(81)] },
  { requirement_id: 8, deployment_run_id: runId, case_key: "Visual review",
    method_name: "Browser", outcome: "passed", happened_at: "2026-09-01T11:00:00Z",
    artifacts: [image(82)] },
  { requirement_id: 7, deployment_run_id: runId, case_key: "Retired check",
    outcome: "passed", superseded_by_requirement_id: 8,
    happened_at: "2026-09-01T09:00:00Z", artifacts: [image(71)] },
];

function row(gateStatus) {
  return {
    id: runId, project: "yoke", flow: "hosted", status: "succeeded",
    current_stage: "complete", target_environment: "prod", stages: [],
    member_items: [{ id: 42, ref: "Item", title: "Carried work", project_id: 1 }],
    gates: [{
      request_id: 91, kind: "qa_needs_review", status: gateStatus,
      subject_context: { requirement_id: 8, artifacts: [image(82)],
        expected_outcome: "The page is readable." },
      actions: gateStatus === "pending" ? ["approve", "reject"] : [],
      can_act: gateStatus === "pending", resolution_action: "approve",
      resolved_by: "Reviewer", resolved_at: "2026-09-01T12:00:00Z",
    }],
  };
}

function render(gateStatus) {
  const documentNode = new FakeDocument();
  const context = { document: documentNode,
    projects: () => [{ id: 1, slug: "yoke" }],
    client: { call: async () => ({ status: 200, envelope: { success: true,
      result: { disposition: "unavailable" } } }) } };
  const facts = { evidence: new Map([[runId, { checks, artifacts: [] }]]),
    flowNames: new Map() };
  return { documentNode, card: shippingRunCard(context, row(gateStatus), ["1"], {
    facts, onGateAction: () => {},
  }) };
}

test("effective run checks exclude replaced requirements and older attempts", () => {
  assert.deepEqual(effectiveRunChecks(checks), [checks[1]]);
});

for (const status of ["pending", "resolved"]) {
  test(`${status} review shares one current screenshot with the checks`, () => {
    const { card } = render(status);
    const qa = byClass(card, "run-qa-section")[0];
    assert.equal(byClass(qa, "run-verdict")[0].textContent, "1 of 1 passed");
    const currentEvidence = qa.children.find((node) =>
      node.classList.contains("review-evidence"));
    assert.deepEqual(byClass(currentEvidence, "review-shot").map(
      (shot) => Number(shot.getAttribute("data-artifact-id"))), [82]);
    assert.equal(byClass(qa, "run-qa-history").length, 1);
    assert.equal(byClass(byClass(qa, "run-qa-history")[0], "review-shot").length, 2);
    assert.equal(byClass(qa, "run-qa-check").length, 3);
    assert.equal(byClass(qa, "review-card").length, 1);
    assert.equal(byClass(qa, "review-action").length, status === "pending" ? 2 : 0);
    assert.equal(byClass(qa, "run-decision-record").length, status === "resolved" ? 1 : 0);
    assert.equal(byClass(card, "shipping-run-evidence").length, 0);
  });
}

test("blank card space opens the run while nested controls keep their action", () => {
  const { documentNode, card } = render("pending");
  const href = byClass(card, "shipping-run-id")[0].href;
  card.dispatchEvent(new Event("click"));
  assert.equal(documentNode.defaultView.location.hash, href);
  documentNode.defaultView.location.hash = "#/unchanged";
  const nestedClick = new Event("click");
  Object.defineProperty(nestedClick, "target", { value: byClass(card, "review-action")[0] });
  card.dispatchEvent(nestedClick);
  assert.equal(documentNode.defaultView.location.hash, "#/unchanged");
  const enter = new Event("keydown");
  Object.defineProperty(enter, "key", { value: "Enter" });
  card.dispatchEvent(enter);
  assert.equal(documentNode.defaultView.location.hash, href);
  documentNode.defaultView.location.hash = "#/unchanged";
  const space = new Event("keydown", { cancelable: true });
  Object.defineProperty(space, "key", { value: " " });
  card.dispatchEvent(space);
  assert.equal(documentNode.defaultView.location.hash, href);
  assert.equal(space.defaultPrevented, true);
  assert.equal(card.getAttribute("tabindex"), "0");
});
