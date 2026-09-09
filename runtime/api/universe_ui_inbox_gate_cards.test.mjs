// What each gate kind SHOWS the person answering it.
//
// The row-level behaviour of the Inbox (counts, resolution, acknowledgement)
// lives in universe_ui_inbox.test.mjs. This file is only about the card body:
// whether an approver is shown the thing they are deciding about.

import assert from "node:assert/strict";
import test from "node:test";

import { appendGateBody } from "../../packages/yoke-core/src/yoke_core/ui/static/decision_gate_body.js";
import { overviewRunCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_overview_cards.js";
import { FakeDocument, byClass, settle } from "./universe_ui_dom_test_support.mjs";
import {
  deploymentRequestRow,
  emptyReleaseRequestRow,
  environmentRunRequestRow,
  inboxClient,
  machineRequestRow,
  qaBareRequestRow,
  qaRequestRow,
  renderInbox,
  requestRow,
  signOffRequestRow,
  undeterminedContentsRequestRow,
} from "./universe_ui_inbox_test_support.mjs";

const gateText = (main) => byClass(main, "gate-body")[0].textContent;

test("a deployment approval names the items it releases, not just the run", async () => {
  const { main } = renderInbox("all", [deploymentRequestRow()]);
  await settle();

  assert.equal(
    byClass(main, "inbox-row-title")[0].textContent,
    "Deploy to prod — approve the prod-deploy stage",
  );
  const subtitle = byClass(main, "inbox-row-subtitle")[0].textContent;
  assert.ok(subtitle.includes("run-20260721-014"), subtitle);
  assert.ok(subtitle.includes("flow yoke-hosted-production"), subtitle);
  assert.ok(subtitle.includes("stage prod-deploy"), subtitle);

  const body = gateText(main);
  assert.ok(body.includes("This run carries 2 changes to prod"), body);
  assert.ok(body.includes("continues into release once you resolve it"), body);
  assert.ok(body.includes("In this release · 2 changes"), body);
  assert.ok(body.includes("YOK-2712"), body);
  assert.ok(body.includes("YOK-2707"), body);
  assert.ok(body.includes("release 0.1.1+launch.379"), body);
  // An item ref inside the release list is an item ref: it links to the item
  // exactly as the row's own does. A commit nobody filed work for has no
  // home, so it stays plain text rather than pointing somewhere invented.
  assert.deepEqual(
    byClass(main, "gate-block-code")
      .filter((node) => node.tagName === "A")
      .map((node) => [node.textContent, node.href]),
    [
      ["YOK-2712", "#/items/2712?project=10"],
      ["YOK-2707", "#/items/2707?project=10"],
      ["YOK-2712", "#/items/2712?project=10"],
      ["YOK-2707", "#/items/2707?project=10"],
    ],
  );
  // Membership and contents are different facts, so the items the pipeline
  // owns stay visible under their own heading rather than being conflated
  // with what ships.
  assert.ok(body.includes("Linked items · 2"), body);
});

test("an environment run reports what it carries, not its empty membership", async () => {
  // The defect this replaces: run membership is empty for an environment run
  // while the release still carries every change merged since the last one,
  // so the card asked someone to approve a release it called empty.
  const { main } = renderInbox("all", [environmentRunRequestRow()]);
  await settle();

  const body = gateText(main);
  assert.ok(body.includes("This run carries 2 changes to stage"), body);
  assert.ok(body.includes("In this release · 2 changes"), body);
  assert.ok(body.includes("YOK-2712"), body);
  // A commit nobody filed work for is still shipping, and is named as one.
  assert.ok(body.includes("9911aa22bb33"), body);
  assert.ok(body.includes("commit with no item reference"), body);
  assert.deepEqual(
    byClass(main, "gate-block-code")
      .filter((node) => node.tagName === "A")
      .map((node) => node.textContent),
    ["YOK-2712"],
  );
  assert.ok(!body.includes("0 changes"), body);
  assert.ok(!body.includes("Linked items"), body);
});

test("an underivable release names its reason instead of reading as empty", async () => {
  const { main } = renderInbox("all", [undeterminedContentsRequestRow()]);
  await settle();

  const body = gateText(main);
  assert.ok(body.includes("could not be determined"), body);
  assert.ok(body.includes("project_checkout_unavailable"), body);
  assert.ok(body.includes("Register this project's checkout"), body);
  // The exact revision, so the approver knows what they would be shipping
  // even though its contents could not be listed.
  assert.ok(body.includes("0.1.2+launch.407"), body);
});

test("a request frozen before contents were derived reports its membership", async () => {
  // Every request stored before the release-contents fact existed carries no
  // `carried` key at all. It knows its membership and nothing else, and says
  // exactly that rather than claiming a derivation it never ran.
  const facts = { ...deploymentRequestRow().subject_context };
  delete facts.carried;
  const { main } = renderInbox("all", [deploymentRequestRow({
    subject_context: facts,
  })]);
  await settle();

  const body = gateText(main);
  assert.ok(body.includes("In this release · 2 items"), body);
  assert.ok(body.includes("This run carries 2 items to prod"), body);
  assert.ok(!body.includes("could not be determined"), body);
  // The producer's own one-line summary repeats the count and destination the
  // card has already given, so it is not echoed.
  assert.ok(!body.includes("2 item(s) ship to prod"), body);
});

test("a sign-off stage is not described as though it deploys", async () => {
  // Not every gated stage precedes a deploy. This one is the flow's last, so
  // every earlier stage has already run and approving completes the run.
  const { main } = renderInbox("all", [signOffRequestRow()]);
  await settle();

  const body = gateText(main);
  assert.ok(
    body.includes("approve-result is the last stage in this flow"),
    body,
  );
  assert.ok(body.includes("rather than starting another deploy"), body);
  assert.ok(!body.includes("continues into"), body);
});

test("a release that carries nothing is not reported as underivable", async () => {
  // The comparison ran and found no new commits. That is an answer, and it
  // reads differently from a derivation that could not run at all.
  const { main } = renderInbox("all", [emptyReleaseRequestRow()]);
  await settle();

  const body = gateText(main);
  assert.ok(body.includes("This run carries no new changes to prod"), body);
  assert.ok(
    body.includes("This release carries no new commits since the previous one"),
    body,
  );
  assert.ok(!body.includes("could not be determined"), body);
  assert.ok(!body.includes("no_new_commits"), body);
});

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
      "This run carries 2 changes to prod",
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

test("a QA gate on a run card carries the evidence the Inbox shows", () => {
  const { card } = renderRunCard(runGate(qaRequestRow()));

  assert.ok(card.className.includes("is-awaiting-review"), card.className);
  assert.equal(byClass(card, "run-gate-name")[0].textContent, "marketing-pages-visual");
  // The same reader, so a reviewer deciding from the pipeline end opens the
  // screenshot exactly as one deciding from the mailbox end does.
  assert.equal(byClass(card, "qa-evidence").length, 3);
  assert.equal(byClass(card, "qa-evidence-open").length, 6);
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
