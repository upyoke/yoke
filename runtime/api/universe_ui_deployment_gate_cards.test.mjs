// What a DEPLOYMENT approval shows the person answering it.
//
// Run membership and release contents are different facts, and whether
// resolving the stage deploys anything at all is a third. These cases are
// exactly where those three diverge, so a card cannot pass them by reading
// any one of them alone. The remaining gate kinds — lifecycle, QA, machine,
// and the run-card surface — live in universe_ui_inbox_gate_cards.test.mjs.

import assert from "node:assert/strict";
import test from "node:test";

import { byClass, settle } from "./universe_ui_dom_test_support.mjs";
import {
  approvalOnlyRequestRow,
  deploymentRequestRow,
  emptyReleaseRequestRow,
  environmentRunRequestRow,
  renderInbox,
  signOffRequestRow,
  undeterminedContentsRequestRow,
  unrecordedEffectRequestRow,
  unsettledEffectRequestRow,
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

test("a gate that deploys nothing says so instead of naming a destination", async () => {
  // The defect this replaces: a run with no destination fell back to the
  // "merge-only" tier label, so an approval that reaches no environment
  // reached its approver titled "Deploy to merge-only".
  const { main } = renderInbox("all", [approvalOnlyRequestRow()]);
  await settle();

  assert.equal(
    byClass(main, "inbox-row-title")[0].textContent,
    "Approval only — deploys nothing",
  );
  const body = gateText(main);
  assert.ok(body.includes("nothing is built, released, or promoted"), body);
  // Reaching no environment is not the same as doing nothing real, and the
  // sentence must not let an approver read it that way.
  assert.ok(body.includes("may still be real"), body);
  // The claim is checkable rather than asserted: the facts behind it are
  // shown, so an approver can see why nothing ships.
  assert.ok(body.includes("Why this deploys nothing"), body);
  assert.ok(body.includes("neither reaches an environment"), body);
  assert.ok(body.includes("names no target environment or tier"), body);
  // No release block: there is no release, and "0 changes" beside it would
  // read as an empty deploy.
  assert.ok(!body.includes("In this release"), body);
  assert.ok(!body.includes("merge-only"), body);
  // The flow's authored name is what says why the flow exists; the
  // derivation never reads it.
  const subtitle = byClass(main, "inbox-row-subtitle")[0].textContent;
  assert.ok(subtitle.includes("Practice: role approval"), subtitle);
});

test("an unsettled consequence is its own answer, not a safe-sounding one", async () => {
  // The flow names a runner this build cannot classify. "Deploys nothing"
  // would be an invented reassurance and "Deploy to merge-only" an invented
  // destination; the honest answer is that the request does not settle it.
  const { main } = renderInbox("all", [unsettledEffectRequestRow()]);
  await settle();

  assert.equal(
    byClass(main, "inbox-row-title")[0].textContent,
    "Approve the review-example stage",
  );
  const body = gateText(main);
  assert.ok(body.includes("could not be established"), body);
  assert.ok(body.includes("treat it as a decision that may deploy"), body);
  assert.ok(body.includes("What could not be established"), body);
  assert.ok(body.includes("publish-example runs mirror-to-cdn"), body);
  // The flow's authored name says "deploys nothing" and the Why-asked line
  // quotes it; what must not appear is the derived claim, which this build
  // cannot make.
  assert.ok(!body.includes("Why this deploys nothing"), body);
  assert.ok(!body.includes("merge-only"), body);
  // An unsettled consequence still lists what the run carries: that is a
  // separate fact and worth reading either way.
  assert.ok(body.includes("In this release"), body);
});

test("a request predating the consequence fact reports it as unrecorded", async () => {
  // Its own stored title says "Deploy to merge-only" — the label a run wears
  // when it names no destination at all. Showing that would hand the reader
  // the invented consequence this classification exists to end.
  const { main } = renderInbox("all", [unrecordedEffectRequestRow()]);
  await settle();

  assert.equal(
    byClass(main, "inbox-row-title")[0].textContent,
    "Approve the review-example stage",
  );
  const body = gateText(main);
  assert.ok(body.includes("recorded before what resolving it deploys"), body);
  assert.ok(body.includes("Read the run's flow before answering"), body);
  assert.ok(!body.includes("Deploy to merge-only"), body);
});

test("a real release that carries nothing is still titled a deploy", async () => {
  // Membership alone cannot tell these apart: this run owns no items and
  // carries no commits, exactly like the approval-only gate above. It targets
  // prod, so it is a release and says so.
  const { main } = renderInbox("all", [emptyReleaseRequestRow()]);
  await settle();

  assert.equal(
    byClass(main, "inbox-row-title")[0].textContent,
    "Deploy to prod — approve the prod-deploy stage",
  );
  const body = gateText(main);
  assert.ok(!body.includes("deploys nothing"), body);
  assert.ok(body.includes("In this release"), body);
});
