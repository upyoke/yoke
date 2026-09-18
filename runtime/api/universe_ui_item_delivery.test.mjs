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

function deliveryClient(item, runs, requests, deliveryDefaults = []) {
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
    if (request.function === "workflows.mechanics.get") {
      return ok({
        delivery_defaults: deliveryDefaults,
        testing_defaults: [], approvers: [],
      });
    }
    if (request.function === "epic_tasks.list.run") return ok({ tasks: [] });
    // The Blitz detail shape reads its execution document; the Dash and
    // Issue shapes do not, and an unanswered read here would break the
    // render before the Delivery panel ever resolved.
    if (request.function === "strategy.execution.get") return ok({ document: null });
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
        created_at: "2026-07-25T12:00:00Z", flow: "acme-stage-then-prod",
        target_environment: "prod" },
      { id: "run-20260726-002", status: "failed", current_stage: "item-qa",
        created_at: "2026-07-26T12:00:00Z", flow: "acme-stage-then-prod",
        target_environment: "prod" },
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
  // The flow the item names deep-links to that definition, not to the catalog.
  const flow = byClass(root, "item-delivery-flow")[0];
  assert.equal(flow.children[1].textContent, "acme-stage-then-prod");
  assert.equal(
    flow.children[1].href, "#/deployments/flows/acme-stage-then-prod?project=7",
  );
  assert.equal(flow.children[2].textContent, "selected on this item");
  assert.deepEqual(
    byClass(root, "item-delivery-role").map((node) => node.textContent),
    ["this item's release", "this item's release"],
  );
  assert.deepEqual(
    byClass(root, "item-delivery-target").map((node) => node.textContent),
    ["prod", "prod"],
  );
});

test("an item with no selection names the project default it actually resolves", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const dash = detailItem("dash");
  dash.deployment_flow = null;
  renderItemDetailView(
    itemContext(documentNode, deliveryClient(dash, [], [], [
      { project_id: 7, project: "acme", workflow_id: "dash",
        flow_id: "acme-default-flow" },
      { project_id: 7, project: "acme", workflow_id: "issue",
        flow_id: "acme-issue-flow" },
    ])),
    root, "7", "ACM-22",
  );
  await settle();
  await settle();

  // The effective binding is read, not asserted, and it is the row for this
  // item's own workflow.
  const flow = byClass(root, "item-delivery-flow")[0];
  assert.equal(flow.children[1].textContent, "acme-default-flow");
  assert.equal(
    flow.children[1].href, "#/deployments/flows/acme-default-flow?project=7",
  );
  assert.equal(
    flow.children[2].textContent, "this project's default for its workflow",
  );
});

test("a project declaring no default for the workflow says so", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const dash = detailItem("dash");
  dash.deployment_flow = null;
  renderItemDetailView(
    itemContext(documentNode, deliveryClient(dash, [], [], [
      { project_id: 7, project: "acme", workflow_id: "issue",
        flow_id: "acme-issue-flow" },
    ])),
    root, "7", "ACM-22",
  );
  await settle();
  await settle();

  assert.match(
    byClass(root, "item-delivery-default")[0].textContent,
    /declares no default for this workflow/,
  );
});

test("an item no release has carried says so", async () => {
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

test("a Blitz item carried by several releases lists every one of them", async () => {
  // Delivery is a fact about an item, not about one workflow: a Blitz item
  // ships through the same releases a Dash or Issue item does, and one that
  // shipped more than once has a history rather than a latest.
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const blitz = detailItem("blitz");
  blitz.deployment_flow = "acme-preview-then-prod";
  const requests = [];
  renderItemDetailView(
    itemContext(documentNode, deliveryClient(blitz, [
      { id: "run-20260724-001", status: "succeeded", current_stage: "complete",
        created_at: "2026-07-24T09:00:00Z", flow: "acme-preview-then-prod" },
      { id: "run-20260726-003", status: "executing", current_stage: "preview-item-qa",
        created_at: "2026-07-26T15:00:00Z", flow: "acme-preview-then-prod" },
      { id: "run-20260725-002", status: "cancelled", current_stage: "stage-deploy",
        created_at: "2026-07-25T11:00:00Z", flow: "acme-preview-then-prod" },
    ], requests)),
    root, "7", "ACM-31",
  );
  await settle();
  await settle();

  // Every release, newest first — a cancelled one in the middle is history,
  // not a gap, and the run in flight is not the only one that answers.
  assert.deepEqual(
    byClass(root, "item-delivery-run").map((node) => node.children[0].textContent),
    ["run-20260726-003", "run-20260725-002", "run-20260724-001"],
  );
  assert.deepEqual(
    byClass(root, "item-delivery-run").map((node) => node.children[1].textContent),
    ["executing", "cancelled", "succeeded"],
  );
  const flow = byClass(root, "item-delivery-flow")[0];
  assert.equal(flow.children[1].textContent, "acme-preview-then-prod");
  assert.equal(flow.children[2].textContent, "selected on this item");
});

test("a carrying run on another flow is participation, not this item's release", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const dash = detailItem("dash");
  dash.deployment_flow = "acme-prod";
  renderItemDetailView(
    itemContext(documentNode, deliveryClient(dash, [
      { id: "run-prod", status: "executing", current_stage: "item-qa",
        created_at: "2026-07-25T12:00:00Z", flow: "acme-prod",
        target_environment: "prod" },
      { id: "run-stage", status: "succeeded", current_stage: "complete",
        created_at: "2026-07-26T12:00:00Z", flow: "acme-stage" },
    ], [])),
    root, "7", "ACM-22",
  );
  await settle();
  await settle();

  assert.deepEqual(
    byClass(root, "item-delivery-run").map((node) => node.children[0].textContent),
    ["run-stage", "run-prod"],
  );
  assert.deepEqual(
    byClass(root, "item-delivery-role").map((node) => node.textContent),
    ["also carried", "this item's release"],
  );
  assert.deepEqual(
    byClass(root, "item-delivery-target").map((node) => node.textContent),
    ["environment unavailable", "prod"],
  );
});
