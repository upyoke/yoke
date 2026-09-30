import assert from "node:assert/strict";
import test from "node:test";

import { FakeDocument, byClass, settle } from "./universe_ui_dom_test_support.mjs";
import { ok, qaRequestRow } from "./universe_ui_inbox_test_support.mjs";
import { renderInboxView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_inbox.js";
import { renderRunDetailView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_run_detail.js";
import { shippingRunCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_work_cards.js";
import { runStageDecisionPresentation } from "../../packages/yoke-core/src/yoke_core/ui/static/review_request_presentation.js";

const RUN = "run-release-decisions";
const CASE = "Release screenshots";

function requests(status = "pending") {
  return ["plan_case", "deployment_stage_acceptance"].map((qaKind, index) => {
    const base = qaRequestRow({ id: 70 + index, project_id: 1, status,
      can_act: status === "pending", resolution_action: "approve", resolved_by: "Reviewer" });
    return { ...base, subject_context: {
      ...base.subject_context, qa_kind: qaKind,
      plan_id: index ? null : 7, case_name: index ? null : CASE,
      method_name: index ? null : "Browser inspection",
      subject: { kind: "deployment_run", deployment_run_id: RUN,
        deployment_member_item_id: null, qa_phase: "post_deploy" },
      artifacts: [],
    } };
  });
}

async function render(surface, status = "pending") {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const rows = requests(status);
  const run = { id: RUN, project: "yoke", flow: "release", status: "executing",
    current_stage: "review", target_environment: "prod", stages: [], member_items: [],
    gates: rows.map((row) => ({ ...row, request_id: row.id })) };
  const answers = [];
  const client = { async call(request) {
    if (request.function === "inbox.list") return ok({ needs_decision: rows, messages: [] });
    if (request.function === "qa.activity.list") return ok({ rows: [] });
    if (request.function === "deployment_runs.list") return ok({ rows: [run], filters: {} });
    if (request.function === "projects.infrastructure.list") return ok({ environments: [] });
    if (request.function === "decision_requests.resolve") {
      answers.push(request.payload);
      return ok({});
    }
    throw new Error(`Unexpected function ${request.function}`);
  } };
  const context = { document: documentNode, client, isMounted: () => true,
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }] };
  if (surface === "Inbox") renderInboxView(context, main, ["1"]);
  if (surface === "Shipping") main.appendChild(shippingRunCard(context, run, ["1"], {
    onGateAction: (gate, action) => answers.push({ request_id: gate.request_id, action }),
  }));
  if (surface === "Run detail") await renderRunDetailView(context, main, ["1"], RUN);
  await settle();
  return { main, answers };
}

const titles = [`Run QA evidence · ${CASE}`, `Run approval · ${RUN}`];
const prompts = [
  "The independent review could not decide. Accept or reject this evidence.",
  "Approve or reject this release.",
];
const buttons = [
  ["Waive evidence review", "Reject evidence", "Accept evidence"],
  ["Waive run approval", "Reject release", "Approve release"],
];

for (const surface of ["Inbox", "Shipping", "Run detail"]) {
  test(`${surface} distinguishes evidence review from run approval without combining decisions`, async () => {
    const { main, answers } = await render(surface);
    assert.deepEqual(byClass(main, "review-title").map((node) => node.textContent), titles);
    const asks = byClass(main, "run-decision-ask");
    assert.equal(asks.length, 2);
    for (let index = 0; index < asks.length; index++) {
      assert.ok(asks[index].textContent.includes(prompts[index]));
      const actions = byClass(asks[index], "review-action");
      assert.deepEqual(actions.map((node) => node.textContent), buttons[index]);
      actions.find((node) => node.getAttribute("data-action") === "approve")
        .dispatchEvent(new Event("click"));
      await settle();
    }
    assert.deepEqual(answers, [
      { request_id: 70, action: "approve" }, { request_id: 71, action: "approve" },
    ]);
  });

  test(`${surface} keeps the distinct subjects after both decisions resolve`, async () => {
    const { main } = await render(surface, "resolved");
    assert.deepEqual(byClass(main, "review-title").map((node) => node.textContent), titles);
    assert.equal(byClass(main, "run-decision-record").length, 2);
    assert.equal(byClass(main, "review-action").length, 0);
  });
}

test("acceptance is identified by its QA kind, not by a missing case name or a verdict reason", () => {
  const [evidence, approval] = requests();
  evidence.subject_context.case_name = null;
  evidence.subject_context.plan_id = null;
  evidence.subject_context.verdict_reason = "configured deployment stage requires authorized human acceptance";
  assert.equal(runStageDecisionPresentation(evidence).title, "Run QA evidence · Browser inspection");
  approval.subject_context.case_name = CASE;
  assert.equal(runStageDecisionPresentation(approval).title, titles[1]);
});

test("item and member evidence reviews keep their existing action wording", () => {
  assert.equal(runStageDecisionPresentation(qaRequestRow()), null);
  const [member] = requests();
  member.subject_context.subject.deployment_member_item_id = 42;
  assert.equal(runStageDecisionPresentation(member), null);
});
