import assert from "node:assert/strict";
import test from "node:test";

import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";
import {
  cardFor, itemReviewRow, member, readingClient, RUN_ID,
} from "./universe_ui_carried_item_test_support.mjs";
import {
  carriedItemReviews,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_carried_item_evidence.js";

for (const runId of [null, "another-release", RUN_ID]) {
  test(`Shipping member reviews require the owning run: ${runId}`, () => {
    const request = itemReviewRow();
    request.subject_context.subject.deployment_run_id = runId;
    const facts = { pendingByItem: new Map([["BUZ-1896", [request]]]) };
    assert.equal(carriedItemReviews(facts, "BUZ-1896", RUN_ID, []).length,
      runId === RUN_ID ? 1 : 0);
  });
}

test("historical stage card offers no controls for an item's premerge review", async () => {
  const document = new FakeDocument();
  const request = itemReviewRow();
  request.subject_context.subject.deployment_run_id = null;
  const client = readingClient({ rows: [], pending: [request] });
  const { card } = await cardFor(document, [member(1896, "BUZ-1896")], client);
  assert.equal(byClass(card, "run-request").length, 0);
  assert.equal(byClass(card, "review-action").length, 0);
});
