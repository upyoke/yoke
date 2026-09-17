// A session card answers two questions with two short statuses: where the
// release carrying its item stands, and whether that item's own scoped QA
// inside that release is accepted. The run half prints the values the
// control plane stores; the QA half prints the acceptance projection's own
// answer, with the blocking reason carried as the pill's title.

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
      live: true, item_qa: "awaiting review",
      item_qa_stage: "preview-item-qa",
      item_qa_reason:
        "stage acceptance requirement #12 awaits authorized human review",
    },
    primary_item_stages: [{ name: "awaiting review", state: "active" }],
  });

  assert.deepEqual(
    byClass(body, "session-delivery-pill").map((node) => node.textContent),
    ["Run: item-qa · executing", "Item QA: awaiting review"],
  );
  assert.equal(byClass(body, "session-delivery-icon").length, 1);
  // The wait itself is on the pill, where a phone reader sees it. Which
  // stage and the sentence behind it ride in the title.
  assert.equal(
    byClass(body, "session-delivery-pill")[1].getAttribute("title"),
    "preview-item-qa: stage acceptance requirement #12 awaits authorized "
      + "human review",
  );
});

test("stored statuses print as stored, not as a friendlier vocabulary", () => {
  // `succeeded` and `failed` are the enum values every other surface gates on
  // and searches by; "done" and "stopped" would be different words for facts
  // a reader cannot then match anywhere else.
  for (const status of ["succeeded", "failed"]) {
    const labels = deliveryStatusLabels({
      primary_item_delivery: {
        run_id: "run-1", status, stage: "complete", live: false,
        item_qa: "accepted",
      },
    });
    assert.deepEqual(
      labels.map((label) => label.text),
      [`Last run: complete · ${status}`, "Item QA: accepted"],
    );
  }
});

test("an accepted member carries no blocking reason to explain", () => {
  const body = render({
    primary_item_delivery: {
      run_id: "run-4", status: "executing", stage: "production", live: true,
      item_qa: "accepted", item_qa_stage: "preview-item-qa",
      item_qa_reason: "",
    },
  });
  assert.equal(
    byClass(body, "session-delivery-pill")[1].getAttribute("title"),
    null,
  );
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

test("a release that has reached no item QA stage reports only the run", () => {
  // Absent is absent. A release standing before its first item QA stage has
  // nothing to report for this member; a placeholder would read as a check
  // nobody has run yet.
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
