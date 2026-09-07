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
  inboxClient,
  machineRequestRow,
  qaBareRequestRow,
  qaRequestRow,
  renderInbox,
  requestRow,
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
  assert.ok(body.includes("This run releases 2 items together to prod"), body);
  assert.ok(body.includes("In this release · 2 items"), body);
  assert.ok(body.includes("YOK-2712"), body);
  assert.ok(body.includes("YOK-2707"), body);
  assert.ok(body.includes("release 0.1.1+launch.379"), body);
});

test("a deployment approval carrying no items says what it is still shipping", async () => {
  const { main } = renderInbox("all", [deploymentRequestRow({
    subject_context: {
      ...deploymentRequestRow().subject_context,
      batch: { item_count: 0, items: [] },
      shipping: {
        release_lineage: null,
        target_environment: "stage",
        summary: "0 item(s) ship to stage.",
      },
    },
  })]);
  await settle();

  // "Releases 0 items" reads as though approving were free. The approver is
  // still advancing a pipeline, and the honest answer is that the run's
  // commits are the payload nobody filed work for.
  const body = gateText(main);
  assert.ok(!body.includes("releases 0 items"), body);
  assert.ok(
    body.includes("carries no recorded items, so what ships to stage is "
      + "whatever its commits contain"),
    body,
  );
  assert.ok(body.includes("In this release · 0 items"), body);
  // The producer's own one-line summary says the count and destination the
  // card has already given twice. Echoing it puts "0 item(s)" back on a card
  // whose whole point is that the count is not what is shipping.
  assert.ok(!body.includes("0 item(s) ship to stage"), body);
});

test("a QA review shows each artifact behind it, openable in place", async () => {
  const { main } = renderInbox("all", [qaRequestRow()]);
  await settle();

  // The stored title is the same fixed sentence for every QA review, so the
  // card names the case instead; a reviewer with three pending reviews could
  // otherwise not tell them apart.
  assert.equal(
    byClass(main, "inbox-row-title")[0].textContent,
    "marketing-pages-visual needs your review",
  );
  const body = gateText(main);
  assert.ok(body.includes("Evidence · 3 artifacts"), body);
  assert.ok(body.includes("Nav collapses at 680px"), body);
  assert.ok(body.includes("Every marketing page renders"), body);
  // One card per artifact, each with its own control: counting the evidence
  // by type told the approver a number and showed them nothing.
  assert.equal(byClass(main, "qa-evidence").length, 3);
  assert.deepEqual(
    byClass(main, "gate-evidence")[0].children
      .filter((node) => node.classList.contains("qa-evidence"))
      .map((card) => byClass(card, "qa-evidence-open")[0].textContent),
    ["screenshot", "screenshot", "log"],
  );
  assert.equal(byClass(main, "gate-evidence-none").length, 0);
});

test("opening a gate artifact reads it and shows the image full-size", async () => {
  const { client, main } = renderInbox("all", [qaRequestRow()]);
  await settle();

  const card = byClass(main, "qa-evidence")[0];
  byClass(card, "qa-evidence-open")[0].dispatchEvent(new Event("click"));
  await settle();

  // The read is addressed at the requirement the gate names, not at an item
  // or session the gate card would have to invent.
  const read = client.requests.filter(
    (request) => request.function === "qa.artifact.read",
  );
  assert.deepEqual(read.map((request) => request.target), [
    { kind: "qa_requirement", qa_requirement_id: 21583 },
  ]);
  assert.deepEqual(read.map((request) => request.payload), [{ artifact_id: 1 }]);

  const full = byClass(card, "qa-evidence-full")[0];
  assert.ok(full, "an image artifact opens at full size");
  assert.equal(full.target, "_blank");
  assert.ok(full.href.startsWith("data:image/png;base64,"), full.href);
  assert.equal(
    full.getAttribute("aria-label"), "Open full image: screenshot",
  );
  const preview = byClass(card, "qa-evidence-preview")[0];
  assert.equal(preview.href, undefined);
  assert.equal(preview.alt, "screenshot");
});

test("a gate artifact whose bytes are elsewhere says where, not nothing", async () => {
  const { main } = renderInbox("all", [qaRequestRow()]);
  await settle();

  // The third fixture artifact reads back as living on its capture machine.
  const card = byClass(main, "qa-evidence")[2];
  byClass(card, "qa-evidence-open")[0].dispatchEvent(new Event("click"));
  await settle();

  assert.equal(
    byClass(card, "qa-evidence-action")[0].textContent, "on studio-mini",
  );
  assert.ok(
    card.textContent.includes("the evidence bytes are not present"),
    card.textContent,
  );
});

test("a QA review with no artifacts refuses instead of looking the same", async () => {
  const { main } = renderInbox("all", [qaBareRequestRow()]);
  await settle();

  assert.equal(byClass(main, "qa-evidence").length, 0);
  const refusal = byClass(main, "gate-evidence-none")[0];
  assert.ok(refusal, "a run with no artifacts must say so");
  assert.ok(
    refusal.textContent.includes("a verdict on nothing"),
    refusal.textContent,
  );
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
  // Why the transition was gated at all: the pinned version and the policy
  // entry that asked. The subtitle carries it, and it names the version a
  // person can look up rather than that version's row id.
  const subtitle = byClass(main, "inbox-row-subtitle")[0].textContent;
  assert.ok(
    subtitle.includes("dash@3 · approval_defaults.reviewing-implementation"),
    subtitle,
  );
  assert.ok(!subtitle.includes("v41"), subtitle);
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
      "This run releases 2 items together to prod",
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
