// A run QA review in the Inbox is titled for its run, lists the run's own
// checks with their own screenshots, folds earlier attempts, and ends with the
// person's decision. Release and work approvals keep their own card.

import assert from "node:assert/strict";
import test from "node:test";

import { byClass, FakeDocument, settle } from "./universe_ui_dom_test_support.mjs";
import { inboxSection, ok, qaRequestRow, requestRow } from "./universe_ui_inbox_test_support.mjs";
import { renderInboxView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_inbox.js";

const RUN = "run-20260927-006";
const image = (id) => ({ id, artifact_type: "screenshot", content_type: "image/png" });

function runReview(overrides = {}) {
  const row = qaRequestRow({ id: 9142, project_id: 10, ...overrides });
  return {
    ...row,
    subject_context: {
      ...row.subject_context,
      requirement_id: 32070,
      subject: { kind: "deployment_run", item_id: null, deployment_member_item_id: null,
        deployment_run_id: RUN, qa_phase: "post_deploy" },
      expected_outcome: "Every admitted case passed against the pinned deployment target.",
      verdict_reason: "configured deployment stage requires authorized human acceptance",
      artifacts: [image(22834), image(22835), image(22840)],
    },
  };
}

const RUN_CHECKS = [
  { requirement_id: 31974, deployment_run_id: RUN, project: "yoke",
    case_key: "current-release-review-state", method_name: "Browser inspection",
    outcome: "passed", verdict_reason: "Shipping shows the approved review.",
    happened_at: "2026-09-27T12:10:00Z", artifacts: [image(22834), image(22835)] },
  { requirement_id: 32001, deployment_run_id: RUN, project: "yoke",
    method_name: "Browser inspection", outcome: "passed",
    happened_at: "2026-09-27T12:12:00Z", artifacts: [image(22840)] },
  { requirement_id: 31900, deployment_run_id: RUN, project: "yoke",
    method_name: "Browser inspection", outcome: "failed", superseded_by_requirement_id: 31974,
    happened_at: "2026-09-27T11:00:00Z", artifacts: [image(22800)] },
];

function render(rows) {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const requests = [];
  const client = {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "inbox.list") {
        return ok({ needs_decision: rows, messages: [], pending_actor_message_count: 0 });
      }
      if (request.function === "qa.activity.list") {
        return ok({ rows: request.payload.deployment_run_id === RUN ? RUN_CHECKS : [] });
      }
      if (request.function === "qa.artifact.read") {
        return ok({ artifact_id: request.payload.artifact_id, disposition: "ready",
          content_type: "image/png", content_base64: "aVZCT1J3MEs=" });
      }
      if (request.function === "decision_requests.resolve") return ok({});
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  renderInboxView({ document: documentNode, client, isMounted: () => true,
    projects: () => [{ id: 10, slug: "yoke", name: "Yoke" }] }, main, ["10"]);
  return { main, client };
}

const shotIds = (node) => byClass(node, "review-shot").map(
  (shot) => Number(shot.getAttribute("data-artifact-id")));

test("an open run QA review lists the run's checks, then asks for the decision", async () => {
  const { main, client } = render([runReview()]);
  await settle();
  const card = byClass(inboxSection(main, "waiting"), "review-card")[0];
  const title = byClass(card, "review-title")[0];
  assert.equal(title.textContent, `Run QA · ${RUN}`);
  assert.equal(title.children[0].href, `#/deployments/runs/${RUN}?project=10`);
  assert.ok(client.requests.some((request) => request.function === "qa.activity.list"
    && request.payload.deployment_run_id === RUN && request.payload.project === "10"));

  const checks = byClass(card, "run-qa-review-checks")[0];
  const current = checks.children.filter((node) => node.classList.contains("run-qa-check"));
  assert.equal(current.length, 2);
  assert.equal(byClass(current[0], "run-qa-check-name")[0].children[0].href,
    "#/qa-activity/31974?project=10");
  assert.equal(byClass(current[0], "run-qa-check-outcome")[0].textContent,
    "screenshots captured · awaiting your approval");
  assert.equal(byClass(current[0], "run-qa-check-reason")[0].textContent,
    "Shipping shows the approved review.");
  // Each screenshot once, under the check that took it.
  assert.deepEqual(shotIds(current[0]), [22834, 22835]);
  assert.deepEqual(shotIds(current[1]), [22840]);
  const history = byClass(checks, "run-qa-history")[0];
  assert.equal(history.children[0].textContent, "1 earlier or superseded check");
  assert.deepEqual(shotIds(history), [22800]);

  const ask = byClass(card, "run-decision-ask")[0];
  assert.equal(ask.children[0].textContent, "Approve or reject the visual result.");
  assert.deepEqual(byClass(ask, "review-action").map((node) => node.textContent),
    ["Waive", "Reject", "Approve"]);
  // No boilerplate, no request-wide strip, no footer run link.
  assert.doesNotMatch(card.textContent, /Every admitted case passed|authorized human acceptance/);
  assert.equal(byClass(card, "review-qa").length, 0);
  assert.equal(byClass(card, "review-links").length, 0);
  assert.equal(byClass(card, "review-side").length, 0);
  assert.equal(new Set(shotIds(card)).size, shotIds(card).length);
});

test("answering the review goes through the Inbox resolver", async () => {
  const { main, client } = render([runReview()]);
  await settle();
  const approve = byClass(inboxSection(main, "waiting"), "review-action")
    .find((node) => node.getAttribute("data-action") === "approve");
  approve.dispatchEvent(new Event("click"));
  await settle();
  const resolve = client.requests.find((request) => request.function === "decision_requests.resolve");
  assert.deepEqual(resolve.payload, { request_id: 9142, action: "approve" });
});

for (const [action, state, outcome] of [
  ["approve", "Approved", "approved"], ["reject", "Rejected", "rejected"],
]) {
  test(`a ${outcome} run QA review records the answer on each check`, async () => {
    const { main } = render([runReview({ status: "resolved", decided_by_you: true,
      your_decision: { action }, actions: [], can_act: false })]);
    await settle();
    const card = byClass(inboxSection(main, "decided"), "review-card")[0];
    assert.equal(byClass(card, "review-state")[0].textContent, state);
    assert.equal(byClass(card, "review-who")[0].textContent, `You ${outcome}`);
    assert.equal(byClass(card, "review-action").length, 0);
    assert.equal(byClass(byClass(card, "run-qa-check")[0], "run-qa-check-outcome")[0]
      .textContent, outcome);
  });
}

test("release approvals and item QA reviews keep the shared request card", async () => {
  const { main } = render([requestRow(), qaRequestRow({ id: 12 })]);
  await settle();
  const cards = byClass(inboxSection(main, "waiting"), "review-card");
  assert.equal(cards.length, 2);
  assert.equal(byClass(inboxSection(main, "waiting"), "run-qa-review").length, 0);
  assert.equal(byClass(cards[1], "review-qa").length, 1);
});

test("an Inbox run review decided with no recorded action never reads approved", async () => {
  const { main } = render([runReview({ status: "resolved", decided_by_you: true,
    your_decision: {}, actions: [], can_act: false })]);
  await settle();
  const card = byClass(inboxSection(main, "decided"), "review-card")[0];
  assert.equal(byClass(byClass(card, "run-qa-check")[0], "run-qa-check-outcome")[0]
    .textContent, "decided · outcome not recorded");
  assert.equal(byClass(card, "review-state")[0].textContent, "Decided");
  assert.equal(byClass(card, "review-who")[0].textContent, "You decided");
});

test("your vote on a review still open for others keeps its checks awaiting approval", async () => {
  const { main } = render([runReview({ status: "pending", decided_by_you: true,
    your_decision: { action: "approve" }, actions: [], can_act: false,
    approval_progress: { mode: "all", required: 2, satisfied: 1, outstanding: ["Quinn"] } })]);
  await settle();
  const card = byClass(inboxSection(main, "decided"), "review-card")[0];
  assert.equal(byClass(byClass(card, "run-qa-check")[0], "run-qa-check-outcome")[0]
    .textContent, "screenshots captured · awaiting your approval");
  assert.equal(byClass(card, "review-state")[0].textContent, "Approved");
  assert.match(byClass(card, "review-who")[0].textContent, /^You approved · 1 of 2 · waiting on Quinn$/);
});

test("a resolved review reads the request's outcome over your own vote", async () => {
  const { main } = render([runReview({ status: "resolved", decided_by_you: true,
    resolution_action: "reject", your_decision: { action: "approve" }, actions: [], can_act: false })]);
  await settle();
  const card = byClass(inboxSection(main, "decided"), "review-card")[0];
  assert.equal(byClass(byClass(card, "run-qa-check")[0], "run-qa-check-outcome")[0]
    .textContent, "rejected");
});
