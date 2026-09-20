// What a bounded read must never cost: another subject's evidence, another
// release's evidence, or anybody's waiting action.
//
// Reading a set of items' QA as one recency page let the busiest subject
// fill the cap and every other requested subject read back as having
// nothing. Bounding per item alone moved the problem to releases. These
// cases hold the shape that answers both, and the rule that survives them:
// history is what a cap may trim, never a live request.

import assert from "node:assert/strict";
import test from "node:test";

import { byClass, FakeDocument, settle } from "./universe_ui_dom_test_support.mjs";
import { qaRequestRow } from "./universe_ui_inbox_test_support.mjs";
import {
  activityRow,
  cardFor,
  itemReviewRow,
  member,
  memberEntry,
  readingClient,
  readingContext,
  RUN_ID,
} from "./universe_ui_carried_item_test_support.mjs";
import {
  loadCarriedItemEvidence,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_carried_item_evidence.js";

test("the read is asked to bound each subject, not the page", async () => {
  const client = readingClient({ rows: [activityRow()] });
  const context = readingContext(new FakeDocument(), client);

  await loadCarriedItemEvidence(context, [member(1896, "BUZ-1896")]);

  const activity = client.requests.find((r) => r.function === "qa.activity.list");
  // With item_ids the server reads this many rows PER ITEM, so a busy
  // subject cannot spend a quiet one's share.
  assert.equal(activity.payload.limit, 20);
  assert.deepEqual(activity.payload.item_ids, [1896]);
});


test("an item whose evidence was cut short says so in its own entry", async () => {
  const documentNode = new FakeDocument();
  const client = readingClient({
    rows: [activityRow()],
    selection: {
      per_group_limit: 20,
      truncated_groups: [{ item_id: 1896, deployment_run_id: null }],
    },
  });
  const { card } = await cardFor(documentNode, [member(1896, "BUZ-1896")], client);
  await settle();

  const evidence = byClass(memberEntry(card), "carried-item-evidence")[0];
  const notes = byClass(evidence, "carried-item-evidence-note")
    .map((node) => node.textContent);
  // The cap is per release, so the note says that rather than naming a
  // count the entry may be showing twice over.
  assert.ok(
    notes.some((text) => /at most 20 checks per release/.test(text)),
    notes.join(" | "),
  );
});


test("a pending review survives its own item's history being cut short", async () => {
  const documentNode = new FakeDocument();
  const client = readingClient({
    // The requirement this review is about is not among the rows that came
    // back — it fell outside the per-item bound.
    rows: [activityRow({ requirement_id: 26134 })],
    selection: { per_item_limit: 20, truncated_item_ids: [1896] },
    pending: [itemReviewRow({ id: 4500 })],
  });
  const { card } = await cardFor(documentNode, [member(1896, "BUZ-1896")], client);
  await settle();

  const evidence = byClass(memberEntry(card), "carried-item-evidence")[0];
  const review = byClass(evidence, "review-card")[0];
  assert.ok(review, "the waiting review is still offered");
  assert.equal(review.getAttribute("data-request-id"), "4500");
});


test("an item with no shown checks but a waiting review still draws it", async () => {
  const documentNode = new FakeDocument();
  const client = readingClient({
    // Nothing relevant to this run came back at all.
    rows: [activityRow({ deployment_run_id: "run-20260910-003" })],
    pending: [itemReviewRow({ id: 4502 })],
  });
  const { card } = await cardFor(documentNode, [member(1896, "BUZ-1896")], client);
  await settle();

  const evidence = byClass(memberEntry(card), "carried-item-evidence")[0];
  assert.ok(evidence, "the entry is drawn for the request alone");
  // Silence is a named state, not a missing caption. The waiting review
  // still sits under that state rather than under a blank title.
  assert.match(
    byClass(evidence, "carried-item-evidence-caption")[0].textContent,
    /never asked/,
  );
  assert.equal(byClass(evidence, "review-card")[0].getAttribute("data-request-id"), "4502");
});

test("a release's own member review survives its item's history being cut short", async () => {
  const documentNode = new FakeDocument();
  const client = readingClient({
    rows: [activityRow({ requirement_id: 26134 })],
    selection: {
      per_group_limit: 20,
      truncated_groups: [{ item_id: 1896, deployment_run_id: RUN_ID }],
    },
    // The producer's shape for a release's per-member check: run scoped, so
    // `item_id` is null and the member field is the only association.
    pending: [qaRequestRow({
      id: 4700,
      status: "pending",
      subject_key: "88888",
      subject_context: {
        ...qaRequestRow().subject_context,
        requirement_id: 88888,
        subject: {
          kind: "deployment_run",
          item_id: null,
          deployment_member_item_id: 1896,
          item_ref: "BUZ-1896",
          item_title: "Carried item",
          deployment_run_id: RUN_ID,
          target_environment: "stage",
          qa_phase: "post_deploy",
        },
      },
    })],
  });
  const { card } = await cardFor(documentNode, [member(1896, "BUZ-1896")], client);
  await settle();

  const evidence = byClass(memberEntry(card), "carried-item-evidence")[0];
  const review = byClass(evidence, "review-card")[0];
  assert.ok(review, "the member review is offered under the item it is about");
  assert.equal(review.getAttribute("data-request-id"), "4700");
});
