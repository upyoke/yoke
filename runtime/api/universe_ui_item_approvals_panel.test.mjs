// An item's own Approvals section draws the same decision record the run
// card and Inbox draw, and answers it through the same resolver: approving
// here resolves that one request id. Only a request for the item's current
// transition offers an answer; an older or reopened one is history.

import assert from "node:assert/strict";
import test from "node:test";

import { FakeDocument, byClass, settle, visibleText } from "./universe_ui_dom_test_support.mjs";
import { itemApprovalsPanel } from "../../packages/yoke-core/src/yoke_core/ui/static/item_view_approvals.js";

const ITEM = { public_ref: "YOK-71", project: { id: 1 } };

function approval(requestId, standing, facts = {}) {
  const pending = standing === "pending";
  return {
    request_id: requestId, kind: "lifecycle_transition_approval", standing,
    status: pending ? "pending" : "resolved", item_status: "release",
    requested_at: "2026-10-23T12:00:00Z",
    subject_context: {
      item_id: 71, item_ref: "YOK-71", from_stage: "release", to_stage: "done",
      evidence: { state: "not_expected", screenshots: [] },
    },
    actions: pending ? ["approve", "reject"] : [],
    can_act: pending,
    deciders: [{ via: "owner", label: "Ben Bauman" }],
    resolution_action: pending ? null : standing === "rejected" ? "reject" : "approve",
    resolved_by: pending ? null : "Ben Bauman",
    resolved_at: pending ? null : "2026-10-23T12:30:00Z",
    ...facts,
  };
}

function context(calls, approvalsAfter = []) {
  return {
    document: new FakeDocument(),
    isMounted: () => true,
    client: {
      async call(request) {
        calls.push(request);
        const result = request.function === "items.detail.get"
          ? { item: { ...ITEM, approvals: approvalsAfter } } : { request_id: 9 };
        return { status: 200, envelope: { success: true, result } };
      },
    },
  };
}

const buttons = (root, action) => byClass(root, "review-action")
  .filter((node) => node.getAttribute("data-action") === action);

test("no requested approval draws no panel", () => {
  const calls = [];
  assert.equal(itemApprovalsPanel(context(calls), { ...ITEM, approvals: [] }), null);
  assert.equal(itemApprovalsPanel(context(calls), ITEM), null);
});

test("a pending approval answers the same request the Inbox answers", async () => {
  const calls = [];
  const view = context(calls, [approval(9, "completed")]);
  const panel = itemApprovalsPanel(view, { ...ITEM, approvals: [approval(9, "pending"), approval(4, "superseded")] });
  const text = visibleText(panel, " ");
  assert.match(text, /release → done · awaiting a decision/);
  assert.match(text, /Earlier decisions/);
  assert.equal(buttons(panel, "approve").length, 1);
  buttons(panel, "approve")[0].dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(calls[0], {
    function: "decision_requests.resolve", payload: { request_id: 9, action: "approve" },
  });
  assert.equal(calls[1].function, "items.detail.get");
  assert.match(visibleText(panel, " "), /release → done · approved · completed/);
  assert.equal(buttons(panel, "approve").length, 0);
});

test("a superseded latest request offers no answer and says nothing is open", () => {
  const panel = itemApprovalsPanel(context([]), { ...ITEM, approvals: [approval(5, "superseded")] });
  assert.match(visibleText(panel, " "), /No approval is open for this item's current stage/);
  assert.equal(buttons(panel, "approve").length, 0);
});

test("an approved request still open reads not yet completed with its decider", () => {
  const panel = itemApprovalsPanel(context([]), { ...ITEM, approvals: [approval(6, "approved")] });
  const text = visibleText(panel, " ");
  assert.match(text, /approved · not yet completed/);
  assert.match(text, /Approved by Ben Bauman/);
});

test("a reader without authority sees who decides instead of controls", () => {
  const panel = itemApprovalsPanel(context([]), {
    ...ITEM, approvals: [approval(7, "pending", { can_act: false })],
  });
  assert.equal(buttons(panel, "approve").length, 0);
  assert.match(visibleText(panel, " "), /owner/);
});
