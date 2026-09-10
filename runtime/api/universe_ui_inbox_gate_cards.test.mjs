// What each gate kind SHOWS the person answering it.
//
// The row-level behaviour of the Inbox (counts, resolution, acknowledgement)
// lives in universe_ui_inbox.test.mjs, and the deployment cards in
// universe_ui_deployment_gate_cards.test.mjs. This file is only about the
// remaining card bodies: whether an approver is shown the thing they are
// deciding about.

import assert from "node:assert/strict";
import test from "node:test";

import { appendGateBody } from "../../packages/yoke-core/src/yoke_core/ui/static/decision_gate_body.js";
import { overviewRunCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_overview_cards.js";
import { FakeDocument, byClass, settle } from "./universe_ui_dom_test_support.mjs";
import {
  deploymentRequestRow,
  inboxClient,
  machineRequestRow,
  qaBareRequestRow,
  qaRequestRow,
  renderInbox,
  requestRow,
} from "./universe_ui_inbox_test_support.mjs";

const gateText = (main) => byClass(main, "gate-body")[0].textContent;


test("a lifecycle approval shows what changed on the branch", async () => {
  const { main } = renderInbox("all", [requestRow()]);
  await settle();

  const body = gateText(main);
  assert.ok(
    body.includes("Moving YOK-1907 from implementing to reviewing-implementation"),
    body,
  );
  assert.ok(body.includes("What changed on the branch"), body);
  assert.ok(body.includes("+412 −87 across 9 files"), body);
  assert.ok(body.includes("runtime/api/inbox.py"), body);
  // Why the transition was gated is prose in the body, not a config entry in
  // the subtitle: the subtitle carries the item's own title.
  const subtitle = byClass(main, "inbox-row-subtitle")[0].textContent;
  assert.ok(
    subtitle.includes("Approve the reviewing-implementation transition"),
    subtitle,
  );
  assert.ok(!subtitle.includes("dash@"), subtitle);
  assert.ok(!subtitle.includes("approval_defaults."), subtitle);
});

test("a laneless transition says so rather than showing an empty diff", async () => {
  // A workflow with no git lane records the absence in the same field a
  // branch would fill, so the gate reads it out instead of drawing a blank
  // block that looks like a failed lookup.
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

  const body = gateText(main);
  assert.ok(
    body.includes("No implementation branch is recorded for this transition."),
    body,
  );
});

// The same four kinds, seen from the delivery end. A gate on a run card is
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
    your_decision: null,
    decided_by_you: false,
    ...overrides,
  };
}

function renderRunCard(gate) {
  const acted = [];
  const card = overviewRunCard(
    { document: new FakeDocument(), client: inboxClient() },
    runRow(gate),
    "all",
    { onGateAction: (row, action) => acted.push([row.request_id, action]) },
  );
  return { acted, card };
}

test("a run stopped on an approval says so and carries the answer", () => {
  const { acted, card } = renderRunCard(runGate(deploymentRequestRow()));

  // The run's own status is still `executing` — the pipeline suspended, it
  // did not fail — so the gate is what the card reports.
  assert.ok(card.className.includes("is-awaiting-approval"), card.className);
  assert.equal(byClass(card, "run-gates-count")[0].textContent, "· 1");
  assert.equal(byClass(card, "run-gate-name")[0].textContent, "prod-deploy");
  assert.equal(byClass(card, "run-gate-note")[0].textContent, "you: project owner");
  assert.ok(
    byClass(card, "run-gate-why")[0].textContent.includes(
      "Deploys 2 changes to prod",
    ),
  );
  // Same labels, same order, same emphasis as the Inbox draws for this
  // decision: the run card is a second view of one gate, not a second
  // recommendation about it.
  const buttons = byClass(card, "run-gate-action");
  assert.deepEqual(buttons.map((node) => node.textContent), ["Reject", "Approve"]);
  assert.deepEqual(
    buttons.map((node) => node.className.includes("is-primary")),
    [false, true],
  );

  // Answered here, not on the way to the run: the card is a link, and the
  // gate's own controls must not navigate out of the answer. What is answered
  // is the decision request, which is why the handler is handed its id.
  buttons[1].dispatchEvent(new Event("click"));
  assert.deepEqual(acted, [[deploymentRequestRow().id, "approve"]]);
});

test("a gate this reader may not answer names who it waits on", () => {
  const { card } = renderRunCard(runGate(deploymentRequestRow(), {
    can_act: false,
    authority_reason: null,
    approval_progress: { waiting_on: "org admin" },
  }));

  assert.equal(byClass(card, "run-gate-note")[0].textContent, "waiting on org admin");
  assert.equal(byClass(card, "run-gate-action").length, 0);
});

test("a QA gate on a run card carries the evidence the Inbox shows", async () => {
  const { card } = renderRunCard(runGate(qaRequestRow()));
  await settle();

  assert.ok(card.className.includes("is-awaiting-review"), card.className);
  assert.equal(byClass(card, "run-gate-name")[0].textContent, "marketing-pages-visual");
  // The same reader, so a reviewer deciding from the pipeline end opens the
  // screenshot exactly as one deciding from the mailbox end does.
  assert.equal(byClass(card, "qa-evidence").length, 3);
  assert.equal(byClass(card, "qa-evidence-preview").length, 2);
});

test("a run with no gate draws no Gates region at all", () => {
  // An empty Gates block on every card would assert a shape the flow does not
  // have, and teach the reader to skip the place the answer appears.
  const { card } = renderRunCard(null);

  assert.equal(byClass(card, "run-gates").length, 0);
  assert.ok(card.className.includes("is-executing"), card.className);
});

test("a machine approval stays the one-line row it is answered as", () => {
  // A machine is admitted from the Machines page, beside the machine itself,
  // where the code and the requester already live. A body here would repeat
  // that page rather than tell the approver anything new.
  const documentNode = new FakeDocument();
  const wrap = documentNode.createElement("article");
  assert.equal(
    appendGateBody({ document: documentNode }, wrap, machineRequestRow()),
    null,
  );
  assert.equal(wrap.children.length, 0);
});
