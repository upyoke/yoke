// On the item page, the run that closes the item states the item's QA as it
// was and where completion stands: "item completed" once that run delivered
// it, otherwise read the way the Shipping card reads it, from the server's
// completion-run QA standing and the item's own done approval standing.

import assert from "node:assert/strict";
import test from "node:test";

import { itemDeliveryPanel } from "../../packages/yoke-core/src/yoke_core/ui/static/item_view_delivery.js";
import { FakeDocument, byClass, settle } from "./universe_ui_dom_test_support.mjs";

const RUN = {
  id: "run-closing", status: "executing", current_stage: "item-qa",
  created_at: "2026-10-23T12:00:00Z", flow: "release", target_environment: "prod",
};

function approval(standing) {
  return {
    request_id: 9, kind: "lifecycle_transition_approval", standing,
    subject_context: { item_ref: "YOK-80", to_stage: "done" },
  };
}

async function outcome(completionQa, approvals = [], completion = RUN) {
  const documentNode = new FakeDocument();
  const panel = itemDeliveryPanel({
    document: documentNode,
    isMounted: () => true,
    client: {
      async call(request) {
        assert.equal(request.function, "deployment_runs.find_by_item");
        const result = { rows: [RUN], completion_run: { id: completion.id, status: completion.status } };
        if (completionQa !== undefined) result.completion_item_qa = completionQa;
        return { status: 200, envelope: { success: true, result } };
      },
    },
  }, {
    public_ref: "YOK-80", project: { id: 1, slug: "yoke" }, workflow: { id: "dash" },
    deployment_flow: "release", approvals,
  });
  await settle();
  return byClass(panel, "item-delivery-outcome")[0] || null;
}

test("no item QA required and a pending approval read as two separate facts", async () => {
  const line = await outcome({ state: "discharged", no_item_qa_required: true, settling: false },
    [approval("pending")]);
  assert.equal(line.textContent, "◐ no item QA required · awaiting approval");
});

test("an approved item still open names where to read its gates", async () => {
  const line = await outcome({ state: "accepted", settling: false }, [approval("approved")]);
  assert.equal(line.textContent, "◐ QA passed · approved · completion pending");
  assert.match(line.title, /yoke items get YOK-80 status/);
});

test("closing needs the run's settlement, and a waiver is not a pass", async () => {
  const line = await outcome({ state: "discharged", settling: true }, [approval("approved")]);
  assert.equal(line.textContent, "◐ QA waived · approved · closing");
});

test("QA not yet clear, or a build without the standing, adds no line", async () => {
  assert.equal(await outcome({ state: "not yet run", settling: false }), null);
  assert.equal(await outcome(undefined), null);
});

test("a delivered run keeps its QA disposition beside the completion", async () => {
  const delivered = { ...RUN, status: "succeeded" };
  const line = await outcome({ state: "discharged", no_item_qa_required: true, settling: false },
    [approval("completed")], delivered);
  assert.equal(line.textContent, "✓ no item QA required · item completed");
  const passed = await outcome({ state: "accepted", settling: false }, [], delivered);
  assert.equal(passed.textContent, "✓ QA passed · item completed");
});
