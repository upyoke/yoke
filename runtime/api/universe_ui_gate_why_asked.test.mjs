// Why an approval reached this reader, and who else could end it.
//
// The block exists because a reader who cannot tell an item-specific
// approval from a workflow default cannot tell whether answering is routine
// or unusual — and because the config entry that selected the approval is
// not something a person can act on.

import assert from "node:assert/strict";
import test from "node:test";

import { byClass, settle } from "./universe_ui_dom_test_support.mjs";
import {
  renderInbox,
  requestRow,
} from "./universe_ui_inbox_test_support.mjs";

test("a gate says where the ask came from and who else can end it", async () => {
  const { main } = renderInbox("all", [requestRow()]);
  await settle();

  const why = byClass(main, "gate-why")[0].textContent;
  // The workflow default, not the config entry that selected it: the stored
  // origin is a closed kind, and "workflow_posture.approval_on_done" named a
  // settings key to a person with no way to act on it.
  assert.ok(
    why.includes("Every dash item needs approval to reach "
      + "reviewing-implementation"),
    why,
  );
  assert.ok(why.includes("that workflow's default, not a setting on this item"), why);
  assert.ok(why.includes("you hold project owner"), why);
  assert.ok(why.includes("dana (project operator)"), why);
  assert.ok(why.includes("Any one approver settles it."), why);
  assert.ok(!why.includes("workflow_posture"), why);
  assert.ok(!why.includes("dash@"), why);
});

test("an item-specific approval is not reported as a workflow default", async () => {
  // The distinction is the whole point of the origin line: an approval this
  // item asked for reads differently from one every item of its workflow gets.
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

  const why = byClass(main, "gate-why")[0].textContent;
  assert.ok(why.includes("This item asks for approval to reach done"), why);
  assert.ok(why.includes("Its workflow does not require one"), why);
  assert.ok(!why.includes("workflow_posture"), why);
});

test("an every-approver gate names what is still outstanding", async () => {
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

  const why = byClass(main, "gate-why")[0].textContent;
  assert.ok(
    why.includes("Every approver must answer: 1 of 2 recorded, waiting on "
      + "project operator."),
    why,
  );
});
