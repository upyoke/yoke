import assert from "node:assert/strict";
import test from "node:test";

import { FakeDocument, allNodes, byClass } from "./universe_ui_dom_test_support.mjs";
import { shippingRunCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_work_cards.js";
import { runGates } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_run_gates.js";

function run(overrides = {}) {
  return {
    id: "run-shipping-proof", project: "yoke", flow: "release",
    status: "executing", current_stage: "approval",
    target_environment: "prod", created_at: "2026-09-26T10:00:00Z",
    stages: [{ name: "approval", state: "active" }],
    member_items: [], gates: [], ...overrides,
  };
}

function render(row) {
  const documentNode = new FakeDocument();
  const context = { document: documentNode, projects: () => [{ id: 1, slug: "yoke" }] };
  return shippingRunCard(context, row, "all", { onGateAction: () => {} });
}

function decision(action) {
  return {
    request_id: 77, kind: "deployment_stage_approval", status: "resolved",
    resolution_action: action, resolved_by: "Ben Bauman",
    resolved_at: "2026-09-26T10:30:00Z", actions: [], can_act: false,
    subject_context: {},
  };
}

function qaDecision(action, memberId = null) {
  return {
    ...decision(action), kind: "qa_needs_review",
    subject_context: { subject: {
      kind: "deployment_run", deployment_run_id: "run-shipping-proof",
      deployment_member_item_id: memberId,
    } },
  };
}

test("pending approval keeps its action and waiting status", () => {
  const card = render(run({ gates: [{
    request_id: 77, kind: "deployment_stage_approval", status: "pending",
    subject_context: {}, actions: ["approve", "reject"], can_act: true,
  }] }));
  assert.ok(card.classList.contains("is-awaiting-approval"));
  assert.equal(byClass(card, "review-action").length, 2);
  assert.equal(byClass(card, "run-decision-record").length, 0);
});

test("pending run QA review keeps its action and waiting status", () => {
  const card = render(run({ gates: [{
    ...qaDecision("approve"), status: "pending",
    actions: ["approve", "reject"], can_act: true,
  }] }));
  assert.ok(card.classList.contains("is-awaiting-review"));
  assert.equal(byClass(card, "review-action").length, 2);
  assert.equal(byClass(card, "run-decision-record").length, 0);
});

for (const memberId of [null, 42]) {
  for (const [action, word] of [["approve", "Approved"], ["reject", "Rejected"]]) {
    test(`${word.toLowerCase()} ${memberId ? "member" : "run"} QA review is read only`, () => {
      const gate = qaDecision(action, memberId);
      const card = render(run({ gates: [gate] }));
      const record = byClass(card, "run-decision-record")[0];
      assert.match(record.textContent, new RegExp(`${word} by Ben Bauman`));
      assert.equal(allNodes(record).filter((node) => node.tagName === "TIME")[0]
        .getAttribute("datetime"), "2026-09-26T10:30:00.000Z");
      assert.equal(byClass(card, "review-action").length, 0);
      assert.deepEqual(runGates(run({ gates: [gate] })), []);
    });
  }
}

for (const [action, word] of [["approve", "Approved"], ["reject", "Rejected"]]) {
  test(`${word.toLowerCase()} approval names actor and time without actions`, () => {
    const card = render(run({ gates: [decision(action)] }));
    const record = byClass(card, "run-decision-record")[0];
    assert.match(record.textContent, new RegExp(`${word} by Ben Bauman`));
    assert.equal(allNodes(record).filter((node) => node.tagName === "TIME")[0]
      .getAttribute("datetime"), "2026-09-26T10:30:00.000Z");
    assert.equal(byClass(card, "review-action").length, 0);
    assert.ok(card.classList.contains("is-executing"));
    assert.deepEqual(runGates(run({ gates: [decision(action)] })), []);
  });
}

test("completed stages and a settlement marker read finalizing while status executes", () => {
  const card = render(run({
    current_stage: "complete", settling_at: "2026-09-26T10:40:00Z",
    stages: [{ name: "approval", state: "complete" }], gates: [decision("approve")],
  }));
  assert.ok(card.classList.contains("is-finalizing"));
  assert.match(byClass(card, "run-finalization-note")[0].textContent,
    /Finalizing member delivery/);
  assert.match(byClass(card, "run-finalization-note")[0].textContent,
    /re-drive this run under the project deploy lock/);
  assert.ok(!card.textContent.includes("succeeded"));
});

test("completed stages awaiting settlement explain the open run", () => {
  const card = render(run({ current_stage: "complete",
    stages: [{ name: "approval", state: "complete" }] }));
  assert.ok(card.classList.contains("is-finalizing"));
  assert.match(byClass(card, "run-finalization-note")[0].textContent,
    /Waiting for final checks/);
});

test("terminal success stays succeeded and has no finalization warning", () => {
  const card = render(run({ status: "succeeded", current_stage: "complete",
    settling_at: "2026-09-26T10:40:00Z", gates: [decision("approve")],
    stages: [{ name: "approval", state: "complete" }] }));
  assert.ok(card.classList.contains("is-succeeded"));
  assert.equal(byClass(card, "run-finalization-note").length, 0);
  assert.equal(byClass(card, "run-decision-record").length, 1);
});
