// A session card answers two questions with two short statuses: where the
// release carrying its item stands, and what that item's own QA inside that
// release found. Both print the values the control plane stores.

import assert from "node:assert/strict";
import test from "node:test";

import {
  deliveryStatusLabels,
  appendSessionDeliveryStatus,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_presentation.js";
import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";

function render(row) {
  const documentNode = new FakeDocument();
  const body = documentNode.createElement("div");
  appendSessionDeliveryStatus(documentNode, body, row);
  return body;
}

test("the release and the member's own QA are two statuses, each short", () => {
  const body = render({
    primary_item_delivery: {
      run_id: "run-20260726-001", status: "executing", stage: "item-qa",
      live: true, item_qa: "needs_review",
    },
    primary_item_stages: [{ name: "awaiting review", state: "active" }],
  });

  assert.deepEqual(
    byClass(body, "session-delivery-pill").map((node) => node.textContent),
    ["Run: item-qa · executing", "Item QA: needs review"],
  );
});

test("stored statuses print as stored, not as a friendlier vocabulary", () => {
  // `succeeded` and `failed` are the enum values every other surface gates on
  // and searches by; "done" and "stopped" would be different words for facts
  // a reader cannot then match anywhere else.
  for (const [status, qa] of [["succeeded", "passed"], ["failed", "failed"]]) {
    const labels = deliveryStatusLabels({
      primary_item_delivery: {
        run_id: "run-1", status, stage: "complete", live: false, item_qa: qa,
      },
    });
    assert.deepEqual(
      labels.map((label) => label.text),
      [`Last run: complete · ${status}`, `Item QA: ${qa}`],
    );
  }
});

test("a finished release is labelled as the last one, not the current one", () => {
  const live = deliveryStatusLabels({
    primary_item_delivery: {
      run_id: "run-2", status: "executing", stage: "stage-deploy", live: true,
    },
  });
  assert.match(live[0].text, /^Run: /);

  const history = deliveryStatusLabels({
    primary_item_delivery: {
      run_id: "run-1", status: "cancelled", stage: "stage-deploy", live: false,
    },
  });
  assert.equal(history[0].text, "Last run: stage-deploy · cancelled");
});

test("a member with no recorded QA in its run reports only the run", () => {
  // Absent QA is absent. Rendering nothing there is the honest answer; a
  // placeholder would read as a state the member never recorded.
  const labels = deliveryStatusLabels({
    primary_item_delivery: {
      run_id: "run-3", status: "executing", stage: "stage-deploy", live: true,
      item_qa: null,
    },
    primary_item_stages: [{ name: "implementing", state: "active" }],
  });
  assert.deepEqual(labels.map((label) => label.text), ["Run: stage-deploy · executing"]);
});

test("a session holding nothing reports nothing rather than an empty pill", () => {
  assert.deepEqual(deliveryStatusLabels({}), []);
  assert.equal(byClass(render({}), "session-delivery").length, 0);
});
