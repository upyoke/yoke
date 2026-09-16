// A release approval in the Inbox, showing what it carries.
//
// Approving a deployment is not approving the QA its carried items recorded,
// and an approver still needs to see that QA to decide. These cases hold
// both halves: the same carried-item block the deployment cards draw, and a
// tile whose own decision stays its own.

import assert from "node:assert/strict";
import test from "node:test";

import { byClass, settle } from "./universe_ui_dom_test_support.mjs";
import { renderInbox } from "./universe_ui_inbox_test_support.mjs";
import {
  deploymentRequestRow,
  undeterminedLineageWithMembersRequestRow,
} from "./universe_ui_deployment_request_fixtures.mjs";
import {
  activityRow,
  artifact,
} from "./universe_ui_carried_item_test_support.mjs";

// The Inbox tile: a release approval shows what it carries as context, and
// keeps its own decision separate from the reviews under it.
function approvalInbox() {
  return renderInbox("all", [deploymentRequestRow()], [
    activityRow({ item_id: 2712, requirement_id: 31200 }),
    activityRow({
      item_id: 2707,
      requirement_id: 31201,
      deployment_run_id: "run-20260721-014",
      artifacts: [artifact(31900, 31201)],
      outcome: "passed",
    }),
  ]);
}

test("a release approval lists what it carries with each item's own QA", async () => {
  const { main } = approvalInbox();
  await settle();

  const carried = byClass(main, "approval-carried")[0];
  assert.ok(carried, "the approval tile carries its release contents");
  assert.match(byClass(carried, "release-batch-title")[0].textContent, /Carries · 2 items/);
  const entries = byClass(carried, "release-member");
  assert.deepEqual(
    entries.map((entry) => entry.children[0].textContent),
    ["YOK-2712", "YOK-2707"],
  );
  // Each entry carries its own item's evidence, under the same association
  // rules the deployment cards use.
  assert.equal(byClass(entries[0], "review-shot").length, 2);
  assert.equal(byClass(entries[1], "review-shot").length, 1);
  // Item evidence stays under its item and deployment verification stays
  // under the run; neither entry repeats that in prose.
  assert.equal(byClass(entries[0], "carried-item-evidence-note").length, 0);
  assert.equal(byClass(entries[1], "carried-item-evidence-note").length, 0);
});

test("approving the release is not approving the items under it", async () => {
  const { main, client } = approvalInbox();
  await settle();

  const tile = byClass(main, "review-card")[0];
  assert.equal(tile.getAttribute("data-request-id"), "12");
  const carried = byClass(tile, "approval-carried")[0];
  // The separation is the card's shape rather than a note on it: each item
  // review below carries its own actions, and the release's own decision is
  // outside that block.
  assert.equal(byClass(carried, "approval-carried-note").length, 0);
  // The tile's own decision is the deployment's, and it is not inside the
  // carried block where an item review would be.
  const tileActions = byClass(tile, "review-action").filter(
    (button) => !byClass(carried, "review-action").includes(button),
  );
  assert.deepEqual(
    tileActions.map((button) => button.getAttribute("data-action")).sort(),
    ["approve", "reject"],
  );
  tileActions.find((button) => button.getAttribute("data-action") === "approve")
    .dispatchEvent(new Event("click"));
  await settle();
  const resolved = client.requests.filter(
    (request) => request.function === "decision_requests.resolve",
  );
  assert.deepEqual(resolved.map((request) => request.payload.request_id), [12]);
});

test("a run whose lineage is unknown still lists the members it declares", async () => {
  const { main } = renderInbox(
    "all",
    [undeterminedLineageWithMembersRequestRow()],
    [
      activityRow({
        item_id: 2712,
        requirement_id: 31200,
        artifacts: [artifact(31900, 31200)],
        outcome: "passed",
      }),
    ],
  );
  await settle();

  const carried = byClass(main, "approval-carried")[0];
  assert.ok(carried, "declared membership is still a known fact");
  assert.match(
    byClass(carried, "overview-run-batch-title")[0].textContent,
    /Carries · 2 items/,
  );
  const entries = byClass(carried, "overview-run-member");
  // Membership names each item as `item_ref`; the entry reads it the same
  // way it reads a derived row's `ref`.
  assert.deepEqual(
    entries.map((entry) => entry.children[0].textContent),
    ["YOK-2712", "YOK-2707"],
  );
  // The block says which of the two records it is showing, rather than
  // letting an approver read declared membership as derived contents.
  assert.match(
    byClass(carried, "approval-carried-note")[0].textContent,
    /release lineage could not be derived/,
  );
  // And the member's own evidence is drawn from the same read.
  assert.equal(byClass(entries[0], "review-shot").length, 1);
});

// A review names the item it is about, so bounding an item's older checks
// must never take its live request off the page with them.
function itemReviewRow(overrides = {}) {
  const base = qaRequestRow();
  return qaRequestRow({
    status: "pending",
    subject_context: {
      ...base.subject_context,
      requirement_id: 99999,
      subject: {
        ...base.subject_context.subject,
        kind: "item",
        item_id: 1896,
        item_ref: "BUZ-1896",
        deployment_run_id: null,
      },
    },
    ...overrides,
  });
}
