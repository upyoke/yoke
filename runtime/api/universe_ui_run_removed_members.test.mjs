import assert from "node:assert/strict";
import test from "node:test";
import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";
import { carriedItems, shippingRunCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_work_cards.js";

const members = [1, 2, 3].map((id) => ({
  public_ref: `ITEM-${id}`, ref: `ITEM-${id}`, project_id: 1, project_sequence: id, title: `Member ${id}`,
}));
function card(row) {
  const document = new FakeDocument();
  return shippingRunCard({ document, projects: () => [{ id: 1, slug: "sample" }] },
    { id: "run-original", project: "sample", status: "succeeded", gates: [], ...row }, ["1"]);
}

test("removed members never contribute to carried counts or their QA", () => {
  const row = {
    member_items: members,
    removed_member_items: [{ ...members[1], later_run_id: "run-later" }, members[2]],
  };
  const node = card(row);
  assert.deepEqual(carriedItems(row), [members[0]]);
  assert.equal(byClass(node, "shipping-run-card-meta")[0].textContent, "1 item");
  assert.equal(byClass(node, "release-batch-title")[0].textContent, "Carries · 1 item");
  assert.equal(byClass(node, "release-member").length, 1);
  const removed = byClass(node, "release-removed")[0];
  assert.equal(byClass(removed, "release-batch-title")[0].textContent, "Removed · 2 items");
  assert.deepEqual(byClass(removed, "release-removed-note").map((n) => n.textContent),
    ["rides run-later", "rides a later release"]);
  assert.equal(byClass(removed, "overview-card-link")[0].href,
    "/deployments/runs/run-later?project=1");
  assert.equal(byClass(removed, "carried-item-evidence").length, 0);
  assert.equal(byClass(removed, "run-qa-check").length, 0);
});

test("all-removed runs do not resurrect historical carried-work members", () => {
  const row = {
    member_items: [],
    carried_work: { items: members },
    removed_member_items: members,
  };
  assert.deepEqual(carriedItems(row), []);
  const node = card(row);
  assert.equal(byClass(node, "shipping-run-card-meta")[0].textContent, "0 items");
  assert.equal(byClass(node, "release-member").length, 0);
  assert.equal(byClass(node, "release-removed-item").length, members.length);
});

test("an older serving response without removal facts keeps its presentation", () => {
  assert.deepEqual(carriedItems({ member_items: members }), members);
  assert.deepEqual(carriedItems({ carried_work: { items: members } }), members);
  assert.equal(byClass(card({}), "shipping-run-card-meta")[0].textContent, "environment run");
});

test("a removed member shows its recorded reason", () => {
  const node = card({
    member_items: [members[0]],
    removed_member_items: [{ ...members[1], reason: "QA failed on stage", later_run_id: "run-later" }],
  });
  assert.equal(byClass(node, "release-removed-note")[0].textContent,
    "QA failed on stage — rides run-later");
});

test("derived carried work is not item QA and says so once", () => {
  const node = card({ member_items: [], carried_work: { items: members }, target_environment: "stage" });
  assert.equal(byClass(node, "release-member").length, members.length);
  assert.equal(byClass(node, "shipping-run-derived").length, 1);
  assert.match(node.textContent, /No item QA owed on this target/);
  assert.doesNotMatch(node.textContent, /item_qa_requirements_unavailable|QA cancelled/);
});
