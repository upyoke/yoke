// Why an approval reached this reader used to live in a Details disclosure.
// That disclosure is gone; these cases hold that the origin and eligibility
// prose is not relocated, and that config keys still do not leak into the
// top-level context line.

import assert from "node:assert/strict";
import test from "node:test";

import { byClass, settle } from "./universe_ui_dom_test_support.mjs";
import {
  renderInbox,
  requestRow,
} from "./universe_ui_inbox_test_support.mjs";

function assertNoWhyAsked(main) {
  assert.equal(byClass(main, "gate-details").length, 0);
  assert.equal(byClass(main, "gate-why").length, 0);
}

test("a gate does not draw Why asked, and context stays free of config keys", async () => {
  const { main } = renderInbox("all", [requestRow()]);
  await settle();

  assertNoWhyAsked(main);
  const context = byClass(main, "review-context")[0].textContent;
  assert.ok(
    context.includes("Approve the reviewing-implementation transition"),
    context,
  );
  assert.ok(!context.includes("workflow_posture"), context);
  assert.ok(!context.includes("dash@"), context);
  assert.ok(!context.includes("approval_defaults."), context);
});

test("an item-specific approval does not relocate its origin into Details", async () => {
  const facts = requestRow().subject_context;
  const { main } = renderInbox("all", [requestRow({
    subject_context: {
      ...facts,
      to_stage: "done",
      approval_source: {
        kind: "item_posture",
        entry: "workflow_posture.approval_on_done",
      },
    },
  })]);
  await settle();

  assertNoWhyAsked(main);
  assert.ok(!byClass(main, "review-context")[0].textContent.includes("workflow_posture"));
});

test("an every-approver gate names outstanding people at the top, not in Details", async () => {
  const { main } = renderInbox("all", [requestRow({
    approval_progress: {
      mode: "all",
      required: 2,
      satisfied: 1,
      outstanding: ["project operator"],
      resolved: false,
    },
  })]);
  await settle();

  assertNoWhyAsked(main);
  const who = byClass(main, "review-who")[0].textContent;
  assert.ok(who.includes("project operator") || who.includes("1 of 2"), who);
});
