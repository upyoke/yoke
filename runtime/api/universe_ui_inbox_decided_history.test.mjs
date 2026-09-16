// What a person can still reach after they have answered.
//
// The Inbox used to remember an answered request only in the page that drew
// it: the server listed pending gates alone, so a reader who settled four
// requests and reloaded landed on an empty history with no way back to what
// they had just decided. The server now serves a short tail of its own
// settled rows beside what still waits, and these cases hold both halves of
// that — the history survives the reload, and a settled gate is not offered
// anywhere as something still needing a review.

import assert from "node:assert/strict";
import test from "node:test";

import { byClass, settle } from "./universe_ui_dom_test_support.mjs";
import {
  inboxSection as section,
  ok,
  qaRequestRow,
  renderInbox,
  requestRow,
} from "./universe_ui_inbox_test_support.mjs";
import { loadPendingReviews } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_run_evidence.js";

function settledRow(overrides = {}) {
  return requestRow({
    status: "resolved",
    decided_by_you: true,
    your_decision: { action: "approve" },
    actions: [],
    can_act: false,
    ...overrides,
  });
}

const WAITING = "waiting";
const DECIDED = "decided";

test("a settled request the server still serves survives a reload", async () => {
  // A freshly loaded page remembers nothing, so anything in the decided
  // list here came back from the server's own record of the answer.
  const { main } = renderInbox("all", [settledRow()]);
  await settle();

  const decided = section(main, DECIDED);
  assert.equal(decided.hidden, false);
  assert.equal(byClass(decided, "review-card").length, 1);
  assert.match(byClass(decided, "review-card")[0].textContent, /You approved/);
  // It is history, not a second chance to answer.
  assert.equal(byClass(decided, "review-action").length, 0);
  assert.equal(byClass(section(main, WAITING), "review-card").length, 0);
});

test("a settled QA review is not offered as one still needing a review", async () => {
  const client = {
    async call() {
      return ok({
        needs_decision: [
          qaRequestRow({ id: 11, status: "pending" }),
          qaRequestRow({
            id: 12,
            status: "resolved",
            decided_by_you: true,
            subject_context: {
              ...qaRequestRow().subject_context,
              requirement_id: 90210,
            },
          }),
        ],
      });
    },
  };
  const pending = await loadPendingReviews({ client }, [10]);

  assert.deepEqual([...pending.keys()], ["21583"]);
  assert.equal(pending.get("90210"), undefined);
});
