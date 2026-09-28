import assert from "node:assert/strict";
import test from "node:test";

import { FakeDocument, allNodes, byClass, settle } from "./universe_ui_dom_test_support.mjs";
import { shippingRunCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_work_cards.js";
import { effectiveRunChecks } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_run_evidence.js";
import { runQaSection } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_run_qa.js";

const runId = "run-current-qa";
const image = (id) => ({ id, artifact_type: "screenshot", content_type: "image/png" });
const checks = [
  { requirement_id: 8, deployment_run_id: runId, project: "yoke",
    case_key: "current-release-review-state", method_name: "Browser inspection",
    outcome: "failed", verdict_reason: "The screenshot could not be read.",
    happened_at: "2026-09-01T10:00:00Z", artifacts: [image(81)] },
  { requirement_id: 8, deployment_run_id: runId, project: "yoke",
    case_key: "current-release-review-state", method_name: "Browser inspection",
    outcome: "passed", verdict_reason: "Every page renders with its data.",
    happened_at: "2026-09-01T11:00:00Z", artifacts: [image(82), image(83)] },
  { requirement_id: 9, deployment_run_id: runId, project: "yoke",
    method_name: "Browser inspection", outcome: "passed",
    happened_at: "2026-09-01T11:05:00Z", artifacts: [image(91)] },
  { requirement_id: 7, deployment_run_id: runId, project: "yoke", case_key: "Retired check",
    method_name: "Browser inspection", outcome: "passed", superseded_by_requirement_id: 8,
    happened_at: "2026-09-01T09:00:00Z", artifacts: [image(71)] },
];

// The decision request froze every screenshot under its own requirement (8),
// including ones requirement 9 captured: ownership comes from the checks.
function row(gateStatus, resolution = "approve") {
  return {
    id: runId, project: "yoke", flow: "hosted", status: "succeeded",
    current_stage: "complete", target_environment: "prod", stages: [],
    member_items: [{ id: 42, ref: "YOK-42", title: "Carried work", project_id: 1,
      project_sequence: 42 }],
    gates: [{
      request_id: 91, kind: "qa_needs_review", status: gateStatus,
      subject_context: { requirement_id: 8,
        artifacts: [image(82), image(83), image(91), image(71)],
        expected_outcome: "Every admitted case passed against the pinned deployment target.",
        verdict_reason: "configured deployment stage requires authorized human acceptance" },
      actions: gateStatus === "pending" ? ["approve", "reject"] : [],
      can_act: gateStatus === "pending", resolution_action: resolution,
      resolved_by: "Ben Bauman", resolved_at: "2026-09-01T12:00:00Z",
    }],
  };
}

function context(documentNode) {
  return { document: documentNode, projects: () => [{ id: 1, slug: "yoke" }],
    client: { call: async () => ({ status: 200, envelope: { success: true,
      result: { disposition: "unavailable" } } }) } };
}

function render(gateStatus, resolution) {
  const documentNode = new FakeDocument();
  const facts = { evidence: new Map([[runId, { checks, artifacts: [] }]]),
    flowNames: new Map() };
  return { documentNode, card: shippingRunCard(context(documentNode),
    row(gateStatus, resolution), ["1"], { facts, onGateAction: () => {} }) };
}

const shotIds = (node) => byClass(node, "review-shot").map(
  (shot) => Number(shot.getAttribute("data-artifact-id")));
const directChecks = (qa) => qa.children.filter(
  (node) => node.classList.contains("run-qa-check"));

test("effective run checks exclude replaced requirements and older attempts", () => {
  assert.deepEqual(effectiveRunChecks(checks), [checks[1], checks[2]]);
});

test("each run screenshot shows once, under the check whose requirement owns it", () => {
  const qa = byClass(render("resolved").card, "run-qa-section")[0];
  const [first, second] = directChecks(qa);
  assert.deepEqual(shotIds(first), [82, 83]);
  assert.deepEqual(shotIds(second), [91]);
  // No request-wide strip, so no tile is filed under a requirement it does
  // not belong to.
  assert.equal(qa.children.some((node) => node.classList.contains("review-evidence")), false);
  const history = byClass(qa, "run-qa-history")[0];
  assert.deepEqual(shotIds(history).sort(), [71, 81]);
  const all = shotIds(qa);
  assert.equal(new Set(all).size, all.length);
});

test("earlier checks fold before the decision", () => {
  const qa = byClass(render("pending").card, "run-qa-section")[0];
  const order = qa.children.map((node) => node.className.split(" ")[0]);
  assert.ok(order.indexOf("run-qa-history") < order.indexOf("run-requests"));
  assert.equal(byClass(qa, "run-qa-history")[0].children[0].textContent,
    "2 earlier or superseded checks");
});

test("a check links its QA case and omits a routine passing reason", () => {
  const qa = byClass(render("resolved").card, "run-qa-section")[0];
  const [first] = directChecks(qa);
  const name = byClass(first, "run-qa-check-name")[0];
  assert.equal(name.textContent, "Browser inspection");
  assert.equal(name.children[0].tagName, "A");
  assert.equal(name.children[0].href, "#/qa-activity/8?project=1");
  assert.equal(byClass(first, "run-qa-check-reason").length, 0);
  assert.equal(allNodes(qa).some((node) => node.tagName === "SUMMARY"
    && node.textContent === "Details"), false);
  assert.doesNotMatch(qa.textContent, /current-release-review-state/);
});

test("a failed check keeps its reason for recovery", () => {
  const qa = byClass(render("resolved").card, "run-qa-history")[0];
  assert.equal(byClass(qa, "run-qa-check-outcome")[0].textContent, "failed");
  assert.equal(byClass(qa, "run-qa-check-reason")[0].textContent,
    "The screenshot could not be read.");
});

test("a resolved review loads frozen screenshots through each case's requirement", async () => {
  const documentNode = new FakeDocument();
  const owners = new Map([[821, 101], [822, 102], [823, 500]]);
  const reads = [];
  const reviewed = { requirement_id: 500, deployment_run_id: runId,
    project: "yoke", method_name: "Browser inspection", outcome: "passed",
    artifacts: [
      { ...image(821), requirement_id: 101 },
      { ...image(822), requirement_id: 102 },
      image(823),
    ] };
  const reviewedRow = { ...row("resolved"), gates: [{
    ...row("resolved").gates[0], subject_context: {
      requirement_id: 500, artifacts: reviewed.artifacts,
    },
  }] };
  const view = { document: documentNode, client: { call: async (request) => {
    reads.push([request.payload.artifact_id, request.target.qa_requirement_id]);
    const authorized = owners.get(request.payload.artifact_id)
      === request.target.qa_requirement_id;
    return authorized
      ? { status: 200, envelope: { success: true, result: {
        disposition: "ready", content_type: "image/png", content_base64: "iVBORw0KGgo=",
      } } }
      : { status: 403, envelope: { success: false, error: {
        message: "artifact does not belong to requirement",
      } } };
  } } };
  const qa = runQaSection(view, reviewedRow, [reviewed], null);
  await settle();
  assert.deepEqual(reads, [[821, 101], [822, 102], [823, 500]]);
  const shots = byClass(qa, "review-shot");
  assert.equal(shots.filter((shot) => shot.classList.contains("is-ready")).length, 3);
  assert.equal(shots.filter((shot) => shot.classList.contains("is-unavailable")).length, 0);
});

test("an open human verdict reads as awaiting approval with a plain request", () => {
  const qa = byClass(render("pending").card, "run-qa-section")[0];
  assert.equal(byClass(qa, "run-verdict")[0].textContent, "Awaiting approval");
  for (const line of directChecks(qa)) {
    assert.equal(byClass(line, "run-qa-check-outcome")[0].textContent,
      "screenshots captured · awaiting approval");
  }
  const ask = byClass(qa, "run-decision-ask")[0];
  assert.equal(ask.children[0].textContent, "Approve or reject the visual result.");
  assert.deepEqual(byClass(ask, "review-action").map((button) => button.textContent),
    ["Reject", "Approve"]);
  assert.doesNotMatch(qa.textContent, /Every admitted case passed|authorized human acceptance/);
  assert.equal(byClass(qa, "run-request-kind").length, 0);
  assert.equal(byClass(qa, "review-links").length, 0);
});

test("an approved human verdict reads approved with the recorded approval", () => {
  const qa = byClass(render("resolved").card, "run-qa-section")[0];
  assert.equal(byClass(qa, "run-verdict")[0].textContent, "2 of 2 approved");
  assert.equal(byClass(directChecks(qa)[0], "run-qa-check-outcome")[0].textContent, "approved");
  assert.match(byClass(qa, "run-decision-record")[0].textContent, /^Approved by Ben Bauman · /);
  assert.equal(byClass(qa, "review-action").length, 0);
  assert.equal(byClass(qa, "review-card").length, 0);
});

test("a rejected human verdict reads rejected", () => {
  const qa = byClass(render("resolved", "reject").card, "run-qa-section")[0];
  assert.equal(byClass(qa, "run-verdict")[0].textContent, "2 of 2 rejected");
  assert.equal(byClass(directChecks(qa)[1], "run-qa-check-outcome")[0].textContent, "rejected");
  assert.match(byClass(qa, "run-decision-record")[0].textContent, /^Rejected by Ben Bauman/);
});

test("agent-only run checks keep their own verdict", () => {
  const documentNode = new FakeDocument();
  const agentRow = { ...row("resolved"), gates: [] };
  const qa = runQaSection(context(documentNode), agentRow, checks, null);
  assert.equal(byClass(qa, "run-verdict")[0].textContent, "2 of 2 passed");
  assert.equal(byClass(directChecks(qa)[0], "run-qa-check-outcome")[0].textContent,
    "verified this release");
});

test("a run with no checks and no decision has no Run QA section", () => {
  const documentNode = new FakeDocument();
  const bare = { ...row("resolved"), gates: [] };
  assert.equal(runQaSection(context(documentNode), bare, [], null), null);
});

test("only the run ID opens run detail; the card itself is not a link", () => {
  const { documentNode, card } = render("pending");
  assert.equal(card.getAttribute("role"), null);
  assert.equal(card.getAttribute("tabindex"), null);
  documentNode.defaultView.location.hash = "#/unchanged";
  card.dispatchEvent(new Event("click"));
  assert.equal(documentNode.defaultView.location.hash, "#/unchanged");
  assert.equal(byClass(card, "shipping-run-id")[0].href,
    "#/deployments/runs/run-current-qa?project=1");
});

test("carried item reference and title both link to the item", () => {
  const { card } = render("resolved");
  const ref = byClass(card, "carried-item-ref")[0];
  const title = byClass(card, "carried-item-title")[0];
  assert.equal(ref.tagName, "A");
  assert.equal(title.tagName, "A");
  assert.equal(title.textContent, "Carried work");
  assert.equal(title.href, ref.href);
});

// Several run QA reviews, or one whose recorded answer is missing or unknown.
function gate(requestId, status, action) {
  return { request_id: requestId, kind: "qa_needs_review", status,
    resolution_action: action, resolved_by: "Ben Bauman",
    resolved_at: "2026-09-01T12:00:00Z", subject_context: { requirement_id: 8 },
    actions: status === "pending" ? ["approve", "reject"] : [],
    can_act: status === "pending" };
}

function sectionWith(gates) {
  const documentNode = new FakeDocument();
  return runQaSection(context(documentNode), { ...row("resolved"), gates }, checks, () => {});
}

const verdictOf = (qa) => byClass(qa, "run-verdict")[0].textContent;
const firstOutcome = (qa) => byClass(directChecks(qa)[0], "run-qa-check-outcome")[0].textContent;

for (const [label, action] of [["missing", undefined], ["empty", ""], ["unknown", "shrug"]]) {
  test(`a decided review with a ${label} action never reads approved`, () => {
    const qa = sectionWith([gate(1, "resolved", action)]);
    assert.equal(verdictOf(qa), "Decided · outcome not recorded");
    assert.equal(firstOutcome(qa), "decided · outcome not recorded");
    assert.doesNotMatch(qa.textContent, /approved|Approved/);
    assert.match(byClass(qa, "run-decision-record")[0].textContent,
      new RegExp(`^Decided \\(${action ? "shrug" : "outcome not recorded"}\\) by Ben Bauman`));
  });
}

test("a rejection outranks another review still pending", () => {
  const qa = sectionWith([gate(1, "resolved", "reject"), gate(2, "pending")]);
  assert.equal(verdictOf(qa), "2 of 2 rejected");
  assert.equal(firstOutcome(qa), "rejected");
});

test("a rejection outranks an approval", () => {
  const qa = sectionWith([gate(1, "resolved", "approve"), gate(2, "resolved", "reject")]);
  assert.equal(verdictOf(qa), "2 of 2 rejected");
});

test("an approval with another review pending still awaits approval", () => {
  const qa = sectionWith([gate(1, "resolved", "approve"), gate(2, "pending")]);
  assert.equal(verdictOf(qa), "Awaiting approval");
  assert.equal(firstOutcome(qa), "screenshots captured · awaiting approval");
});
