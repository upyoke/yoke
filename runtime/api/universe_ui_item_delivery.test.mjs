// An item page says how the work ships: the flow it is bound to, and every
// release that has carried it, newest first.

import assert from "node:assert/strict";
import test from "node:test";

import {
  renderItemDetailView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_items.js";
import {
  FakeDocument,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  detailItem,
  itemContext,
  itemText,
} from "./universe_ui_items_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });

function deliveryClient(item, runs, requests) {
  return async (request) => {
    requests.push(request);
    if (request.function === "items.detail.get") return ok({ item });
    if (request.function === "deployment_runs.find_by_item") {
      return ok({
        item_id: 51,
        fields: ["id", "status", "current_stage", "created_at"],
        rows: runs,
      });
    }
    if (request.function === "qa.artifact.read") {
      return ok({ disposition: "unavailable" });
    }
    if (request.function === "inbox.list") return ok({ needs_decision: [] });
    if (request.function === "sessions.list") return ok({ rows: [] });
    if (request.function === "epic_tasks.list.run") return ok({ tasks: [] });
    throw new Error(`unexpected function ${request.function}`);
  };
}

test("a Dash item lists its releases newest first and names its flow", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const dash = detailItem("dash");
  dash.deployment_flow = "acme-stage-then-prod";
  const requests = [];
  renderItemDetailView(
    itemContext(documentNode, deliveryClient(dash, [
      { id: "run-20260725-001", status: "succeeded", current_stage: "complete",
        created_at: "2026-07-25T12:00:00Z" },
      { id: "run-20260726-002", status: "failed", current_stage: "item-qa",
        created_at: "2026-07-26T12:00:00Z" },
    ], requests)),
    root, "7", "ACM-22",
  );
  await settle();
  await settle();

  // The releases are read through the item's own public ref.
  assert.deepEqual(
    requests.find((r) => r.function === "deployment_runs.find_by_item").target,
    { kind: "item", public_ref: "ACM-22", project_id: "7" },
  );
  assert.deepEqual(
    byClass(root, "item-delivery-run").map((node) => node.children[0].textContent),
    ["run-20260726-002", "run-20260725-001"],
  );
  assert.equal(
    byClass(root, "item-delivery-run")[0].children[0].href,
    "#/deployments/runs/run-20260726-002?project=7",
  );
  const flow = byClass(root, "item-delivery-flow")[0];
  assert.equal(flow.children[1].textContent, "acme-stage-then-prod");
  assert.equal(flow.children[1].href, "#/deployments/flows?project=7");
});

test("an item with no release says so, and an unselected flow is not no flow", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const dash = detailItem("dash");
  dash.deployment_flow = null;
  renderItemDetailView(
    itemContext(documentNode, deliveryClient(dash, [], [])), root, "7", "ACM-22",
  );
  await settle();
  await settle();

  assert.match(itemText(root), /No release has carried this item\./);
  assert.match(
    byClass(root, "item-delivery-default")[0].textContent,
    /none selected on this item — its workflow's project default applies/,
  );
});

test("a Task item gains no delivery panel from a project default", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const requests = [];
  renderItemDetailView(
    itemContext(documentNode, deliveryClient(detailItem("task"), [], requests)),
    root, "7", "ACM-22",
  );
  await settle();
  await settle();

  assert.equal(byClass(root, "item-delivery-flow").length, 0);
  assert.equal(
    requests.filter((r) => r.function === "deployment_runs.find_by_item").length, 0,
  );
});
