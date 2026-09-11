// What a DEPLOYMENT approval shows at the top of the shared request card.
//
// Run membership and release contents used to live inside a Details
// disclosure. That disclosure is gone; these cases hold the remaining
// top-level facts that still tell the shapes apart. The remaining gate
// kinds — lifecycle, QA, machine, and the run-card surface — live in
// universe_ui_inbox_gate_cards.test.mjs.

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

const gateText = (main) => byClass(main, "review-card")[0].textContent;

function assertNoDetails(host) {
  assert.equal(byClass(host, "gate-details").length, 0);
  assert.equal(byClass(host, "gate-why").length, 0);
  assert.equal(byClass(host, "gate-block-code").length, 0);
}

test("a deployment approval names the destination at the top and has no Details", async () => {
  const { main } = renderInbox("all", [deploymentRequestRow()]);
  await settle();

  assert.equal(
    byClass(main, "review-title")[0].textContent,
    "Approve prod deploy",
  );
  const subtitle = byClass(main, "review-context")[0].textContent;
  assert.ok(subtitle.includes("yoke-hosted-production"), subtitle);
  assert.ok(subtitle.includes("to prod"), subtitle);
  assert.ok(!subtitle.includes("run-20260721-014"), subtitle);
  assert.ok(!subtitle.includes("prod-deploy"), subtitle);
  assert.ok(byClass(main, "review-kind")[0].textContent.startsWith("Release approval"));
  assert.equal(
    byClass(main, "review-effect")[0].textContent, "Deploys 2 changes to prod.",
  );
  const body = gateText(main);
  assert.ok(!body.includes("This run carries 2 changes to prod"), body);
  assert.ok(!body.includes("In this release · 2 changes"), body);
  assert.ok(!body.includes("Linked items · 2"), body);
  assertNoDetails(main);
});

test("an environment run still names what it deploys, not empty membership", async () => {
  const { main } = renderInbox("all", [environmentRunRequestRow()]);
  await settle();

  assert.equal(
    byClass(main, "review-effect")[0].textContent,
    "Deploys 2 changes to stage.",
  );
  const body = gateText(main);
  assert.ok(!body.includes("0 changes"), body);
  assert.ok(!body.includes("Linked items"), body);
  assert.ok(!body.includes("9911aa22bb33"), body);
  assertNoDetails(main);
});

test("an underivable release says so in the one-line effect", async () => {
  const { main } = renderInbox("all", [undeterminedContentsRequestRow()]);
  await settle();

  assert.equal(
    byClass(main, "review-effect")[0].textContent,
    "Deploys to stage; release contents are unknown.",
  );
  assert.ok(!gateText(main).includes("project_checkout_unavailable"));
  assertNoDetails(main);
});

test("a request frozen before contents were derived still deploys two items", async () => {
  const facts = { ...deploymentRequestRow().subject_context };
  delete facts.carried;
  const { main } = renderInbox("all", [deploymentRequestRow({
    subject_context: facts,
  })]);
  await settle();

  assert.equal(
    byClass(main, "review-effect")[0].textContent,
    "Deploys to prod; release contents are unknown.",
  );
  assert.ok(!gateText(main).includes("could not be determined"));
  assertNoDetails(main);
});

test("a sign-off stage keeps the same top-level deploy line as the release", async () => {
  const { main } = renderInbox("all", [signOffRequestRow()]);
  await settle();

  assert.equal(
    byClass(main, "review-effect")[0].textContent, "Deploys 2 changes to prod.",
  );
  assert.ok(!gateText(main).includes("approve-result is the last stage"));
  assertNoDetails(main);
});

test("a release that carries nothing is still a deploy, not underivable", async () => {
  const { main } = renderInbox("all", [emptyReleaseRequestRow()]);
  await settle();

  assert.equal(
    byClass(main, "review-effect")[0].textContent, "Deploys 0 changes to prod.",
  );
  const body = gateText(main);
  assert.ok(!body.includes("could not be determined"), body);
  assert.ok(!body.includes("no_new_commits"), body);
  assertNoDetails(main);
});

test("a gate that deploys nothing says so at the top, not as Details", async () => {
  const { main } = renderInbox("all", [approvalOnlyRequestRow()]);
  await settle();

  assert.equal(
    byClass(main, "review-title")[0].textContent,
    "Approve review example",
  );
  assert.equal(
    byClass(main, "review-effect")[0].textContent,
    "Deploys nothing. Approving lets the run finish.",
  );
  const body = gateText(main);
  assert.ok(!body.includes("Why this deploys nothing"), body);
  assert.ok(!body.includes("In this release"), body);
  assert.ok(!body.includes("merge-only"), body);
  const subtitle = byClass(main, "review-context")[0].textContent;
  assert.ok(subtitle.includes("Practice: role approval"), subtitle);
  assertNoDetails(main);
});

test("an unsettled consequence is its own top-level answer", async () => {
  const { main } = renderInbox("all", [unsettledEffectRequestRow()]);
  await settle();

  assert.equal(
    byClass(main, "review-title")[0].textContent,
    "Approve review example",
  );
  assert.equal(
    byClass(main, "review-effect")[0].textContent,
    "Deployment effect is unknown. Treat this as a deploy decision.",
  );
  const body = gateText(main);
  assert.ok(!body.includes("Why this deploys nothing"), body);
  assert.ok(!body.includes("merge-only"), body);
  assert.ok(!body.includes("In this release"), body);
  assertNoDetails(main);
});

test("membership no longer appears as a Details block", async () => {
  const row = {
    ...approvalOnlyRequestRow(),
    subject_context: {
      ...approvalOnlyRequestRow().subject_context,
      batch: {
        item_count: 2,
        items: [
          { item_id: 2712, item_ref: "YOK-2712", title: "Served context window" },
          { item_id: 2707, item_ref: "YOK-2707", title: "Messages address actors" },
        ],
      },
    },
  };
  const { main } = renderInbox("all", [row]);
  await settle();

  const body = gateText(main);
  assert.ok(!body.includes("Linked items · 2"), body);
  assert.ok(!body.includes("In this release"), body);
  assertNoDetails(main);
});

test("a request predating the consequence fact is not titled merge-only", async () => {
  const { main } = renderInbox("all", [unrecordedEffectRequestRow()]);
  await settle();

  assert.equal(
    byClass(main, "review-title")[0].textContent,
    "Approve review example",
  );
  assert.ok(!gateText(main).includes("Deploy to merge-only"));
  assertNoDetails(main);
});

test("a real release that carries nothing is still titled a deploy", async () => {
  const { main } = renderInbox("all", [emptyReleaseRequestRow()]);
  await settle();

  assert.equal(
    byClass(main, "review-title")[0].textContent,
    "Approve prod deploy",
  );
  assert.ok(!gateText(main).includes("deploys nothing"));
  assertNoDetails(main);
});
