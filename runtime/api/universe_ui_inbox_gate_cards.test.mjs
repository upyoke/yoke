// What each request kind SHOWS the person answering it, and how a run card
// folds the same request in.
//
// The card-level behaviour of the Inbox (counts, resolution, acknowledgement)
// lives in universe_ui_inbox.test.mjs, and the deployment cards in
// universe_ui_deployment_gate_cards.test.mjs. This file is about the
// remaining card bodies — whether an approver is shown the thing they are
// deciding about — and about the run card being a second view of one
// request, not a second recommendation about it.

import assert from "node:assert/strict";
import test from "node:test";

import { overviewRunCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_overview_cards.js";
import { FakeDocument, byClass, settle } from "./universe_ui_dom_test_support.mjs";
import {
  deploymentRequestRow,
  inboxClient,
  qaRequestRow,
  renderInbox,
  requestRow,
} from "./universe_ui_inbox_test_support.mjs";

const cardText = (main) => byClass(main, "review-card")[0].textContent;

function assertNoDetails(host) {
  assert.equal(byClass(host, "gate-details").length, 0);
  assert.equal(byClass(host, "gate-why").length, 0);
}


test("a work approval names the transition at the top and has no Details", async () => {
  const { main } = renderInbox("all", [requestRow()]);
  await settle();

  const body = cardText(main);
  assert.equal(
    byClass(main, "review-effect")[0].textContent,
    "Moves the item to reviewing-implementation. Deploys nothing.",
  );
  assert.ok(!body.includes("What changed on the branch"), body);
  assert.ok(!body.includes("runtime/api/inbox.py"), body);
  assertNoDetails(main);
  // Why the transition was gated used to live in Details; the context
  // still carries the item's own title, not a config entry.
  const context = byClass(main, "review-context")[0].textContent;
  assert.ok(
    context.includes("Approve the reviewing-implementation transition"),
    context,
  );
  assert.ok(!context.includes("dash@"), context);
  assert.ok(!context.includes("approval_defaults."), context);
});

test("a laneless transition still names the move and has no empty-diff Details", async () => {
  // A workflow with no git lane used to fill Details with that absence.
  // The top-level effect is the remaining fact; Details is gone.
  const { main } = renderInbox("all", [requestRow({
    subject_context: {
      ...requestRow().subject_context,
      branch_changes: {
        branch: null,
        commit_sha: null,
        touched_files: [],
        summary: "No implementation branch is recorded for this transition.",
      },
    },
  })]);
  await settle();

  assert.equal(
    byClass(main, "review-effect")[0].textContent,
    "Moves the item to reviewing-implementation. Deploys nothing.",
  );
  assert.ok(
    !cardText(main).includes("No implementation branch is recorded for this transition."),
  );
  assertNoDetails(main);
});

// The same kinds, seen from the delivery end. A request on a run card is
// the Inbox decision reached from the pipeline it stopped, so both surfaces
// are given the same subject_context and asked what they show.
function runRow(gate) {
  return {
    id: "run-20260721-014",
    flow: "yoke-hosted-production",
    target_environment: "prod",
    status: "executing",
    created_at: "2026-07-26T10:00:00Z",
    gates: gate ? [gate] : [],
  };
}

function runGate(row, overrides = {}) {
  return {
    request_id: row.id,
    kind: row.kind,
    subject_context: row.subject_context,
    actions: row.actions,
    approval_progress: {},
    can_act: true,
    authority_reason: "project owner",
    deciders: row.deciders,
    your_decision: null,
    decided_by_you: false,
    ...overrides,
  };
}

function renderRunCard(gate) {
  const acted = [];
  const card = overviewRunCard(
    { document: new FakeDocument(), client: inboxClient(), projects: () => [] },
    runRow(gate),
    "all",
    { onGateAction: (row, action) => acted.push([row.request_id, action]) },
  );
  return { acted, card };
}

test("a run stopped on an approval folds the request in and carries the answer", () => {
  const { acted, card } = renderRunCard(runGate(deploymentRequestRow()));

  // The run's own status is still `executing` — the pipeline suspended, it
  // did not fail — so the request is what the card reports.
  assert.ok(card.className.includes("is-awaiting-approval"), card.className);
  assert.equal(byClass(card, "run-request-kind")[0].textContent, "Release approval");
  const request = byClass(card, "review-card")[0];
  // Folded in: the run card is the frame, so the request draws no head and
  // no second box of its own.
  assert.ok(request.classList.contains("inline"), request.className);
  assert.equal(byClass(request, "review-head").length, 0);
  assert.equal(byClass(request, "review-effect")[0].textContent, "Deploys 2 changes to prod.");
  assertNoDetails(request);
  // Same labels, same order, same emphasis as the Inbox draws for this
  // decision.
  const buttons = byClass(card, "review-action");
  assert.deepEqual(buttons.map((node) => node.textContent), ["Reject", "Approve"]);
  assert.deepEqual(
    buttons.map((node) => node.className.includes("primary")),
    [false, true],
  );

  // Answered here, not on the way to the run: the card is a link, and the
  // request's own controls must not navigate out of the answer. What is
  // answered is the decision request, which is why the handler is handed it.
  buttons[1].dispatchEvent(new Event("click"));
  assert.deepEqual(acted, [[deploymentRequestRow().id, "approve"]]);
});

test("a request this reader may not answer names who it waits on and offers nothing", () => {
  const { card } = renderRunCard(runGate(deploymentRequestRow(), {
    can_act: false,
    authority_reason: null,
    deciders: [{ actor_id: 9, label: "quinn", via: "org admin", is_you: false }],
  }));

  assert.equal(byClass(card, "review-who")[0].textContent, "Any org admin can approve");
  assert.equal(byClass(card, "review-action").length, 0);
});

test("a QA review on a run card carries the evidence the Inbox shows", async () => {
  const { card } = renderRunCard(runGate(qaRequestRow()));
  await settle();

  assert.ok(card.className.includes("is-awaiting-review"), card.className);
  assert.equal(byClass(card, "run-request-kind")[0].textContent, "QA review");
  const facts = byClass(card, "review-qa")[0].textContent;
  assert.ok(facts.includes("YOK-1907 · Approval evidence review"), facts);
  assert.ok(facts.includes("Nav collapses at 680px"), facts);
  // The same strip, so a reviewer deciding from the pipeline end opens the
  // screenshot exactly as one deciding from the mailbox end does.
  assert.equal(byClass(card, "review-shot").length, 2);
  assert.equal(byClass(card, "review-text-chip").length, 1);
  assert.deepEqual(
    byClass(card, "review-action").map((node) => node.textContent),
    ["Waive", "Reject", "Approve"],
  );
  assertNoDetails(card);
});

test("a run with no request draws no request region at all", () => {
  // An empty region on every card would assert a shape the flow does not
  // have, and teach the reader to skip the place the answer appears.
  const { card } = renderRunCard(null);

  assert.equal(byClass(card, "run-requests").length, 0);
  assert.equal(byClass(card, "review-card").length, 0);
  assert.ok(card.className.includes("is-executing"), card.className);
});
