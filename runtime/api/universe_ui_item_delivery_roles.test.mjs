import assert from "node:assert/strict";
import test from "node:test";
import { itemDeliveryPanel } from "../../packages/yoke-core/src/yoke_core/ui/static/item_view_delivery.js";
import { relativeAgePhrase } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_time.js";
import { FakeDocument, byClass, settle } from "./universe_ui_dom_test_support.mjs";

async function panel(rows, completion, selected = "own-prod") {
  const documentNode = new FakeDocument();
  const root = itemDeliveryPanel({
    document: documentNode, isMounted: () => true,
    client: { async call(request) {
      assert.equal(request.function, "deployment_runs.find_by_item");
      return { status: 200, envelope: { success: true,
        result: { rows, completion_run: completion } } };
    } },
  }, { public_ref: "example", project: { id: 7 },
    completion_flow: selected, completion_flow_source: "item" });
  await settle();
  return root;
}

const created = "2026-01-01T00:00:00Z";
const completed = "2026-09-30T00:00:00Z";
const delivered = { id: "carrier", flow: "shared-release", status: "succeeded",
  current_stage: "complete", target_environment: "prod",
  created_at: created, completed_at: completed };

test("cross-project delivery names the actual carrier and the unused selected flow", async () => {
  const root = await panel([delivered], delivered);
  assert.equal(byClass(root, "item-delivery-role")[0].textContent, "Delivered by");
  assert.equal(byClass(root, "item-delivery-run-flow")[0].textContent,
    "shared-release → prod");
  const selected = byClass(root, "item-delivery-flow")[0];
  assert.equal(selected.children[0].textContent, "Item’s flow");
  assert.equal(selected.children[1].textContent, "own-prod");
  assert.equal(selected.children[2].textContent, "not used: delivered by the run above");
  assert.equal(byClass(root, "item-delivery-when")[0].textContent,
    `finished ${relativeAgePhrase(completed)}`);
  assert.equal(byClass(root, "item-delivery-stage").length, 0);
});

test("delivery on the selected flow omits the redundant flow row", async () => {
  const run = { ...delivered, flow: "own-prod" };
  const root = await panel([run], run);
  assert.equal(byClass(root, "item-delivery-flow").length, 0);
  assert.equal(byClass(root, "item-delivery-role")[0].textContent, "Delivered by");
});

test("in-flight completion authority says Delivering with stage and start time", async () => {
  const started = "2026-09-29T00:00:00Z";
  const run = { ...delivered, status: "executing", current_stage: "item-qa",
    started_at: started, completed_at: "" };
  const root = await panel([run], run);
  assert.equal(byClass(root, "item-delivery-role")[0].textContent, "Delivering");
  assert.equal(byClass(root, "item-delivery-when")[0].textContent,
    `at item-qa · started ${relativeAgePhrase(started)}`);
  assert.equal(byClass(root, "item-delivery-flow-source")[0].textContent,
    "selected on this item");
});

test("a cancelled duplicate is Also in and ended uses completion time", async () => {
  const cancelled = { ...delivered, id: "duplicate", status: "cancelled",
    created_at: "2026-02-01T00:00:00Z" };
  const root = await panel([delivered, cancelled], delivered);
  assert.deepEqual(byClass(root, "item-delivery-role").map(n => n.textContent),
    ["Also in", "Delivered by"]);
  assert.equal(byClass(root, "item-delivery-when")[0].textContent,
    `ended ${relativeAgePhrase(completed)}`);
  assert.doesNotMatch(root.textContent, /complete ·|also carried|this item's release/);
});

test("failed runs end, and missing terminal timestamps never use creation time", async () => {
  const root = await panel([{ ...delivered, status: "failed", completed_at: "" }], null);
  assert.equal(byClass(root, "item-delivery-role")[0].textContent, "Also in");
  assert.equal(byClass(root, "item-delivery-when")[0].textContent, "ended time unavailable");
});

test("a queued delivering run uses creation time before it starts", async () => {
  const run = { ...delivered, status: "created", current_stage: "", started_at: "" };
  const root = await panel([run], run);
  assert.equal(byClass(root, "item-delivery-when")[0].textContent,
    `started ${relativeAgePhrase(created)}`);
});
