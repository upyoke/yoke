// A session card answers two questions with two short statuses: where the
// release carrying its item has got to, and where the item itself has.

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

test("the release and the item are two statuses, each short", () => {
  const body = render({
    primary_item_delivery: {
      run_id: "run-20260726-001", status: "executing", stage: "stage-item-qa",
    },
    primary_item_stages: [
      { name: "implementing", state: "complete" },
      { name: "awaiting review", state: "active" },
      { name: "done", state: "pending" },
    ],
  });

  assert.deepEqual(
    byClass(body, "session-delivery-pill").map((node) => node.textContent),
    ["Run: stage-item-qa · running", "Item: awaiting review"],
  );
});

test("an item no release carries reports only the item", () => {
  const labels = deliveryStatusLabels({
    primary_item_stages: [{ name: "implementing", state: "active" }],
  });
  assert.deepEqual(labels.map((label) => label.text), ["Item: implementing"]);
});

test("a session holding nothing reports nothing rather than an empty pill", () => {
  assert.deepEqual(deliveryStatusLabels({}), []);
  assert.equal(byClass(render({}), "session-delivery").length, 0);
});

test("a stopped stage is the status the release reports", () => {
  const labels = deliveryStatusLabels({
    primary_item_delivery: {
      run_id: "run-20260726-002", status: "failed", stage: "production",
    },
    primary_item_stages: [{ name: "awaiting deploy", state: "failed" }],
  });
  assert.deepEqual(
    labels.map((label) => label.text),
    ["Run: production · stopped", "Item: awaiting deploy"],
  );
});
