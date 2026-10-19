import assert from "node:assert/strict";
import test from "node:test";

import {
  renderItemDetailView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_items.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  detailItem,
  itemContext,
  itemText,
} from "./universe_ui_items_test_support.mjs";

async function renderOwner(owner) {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const item = { ...detailItem("dash"), ...owner, claim: null };
  renderItemDetailView(itemContext(documentNode, async () => ({
    status: 200,
    envelope: { success: true, result: { item } },
  })), root, "7", "ACM-22");
  await settle();
  const cells = allNodes(byClass(root, "item-facts")[0])
    .filter((node) => node.tagName === "TH" || node.tagName === "TD")
    .map((node) => node.textContent);
  return { ownerFact: cells[cells.indexOf("Owner") + 1], text: itemText(root) };
}

test("item detail shows the owner as name plus actor id", async () => {
  const { ownerFact, text } = await renderOwner({
    owner_actor_id: 2, owner_name: "Ben Bauman",
    owner_label: "Ben Bauman (actor id: 2)",
  });
  assert.equal(ownerFact, "Ben Bauman (actor id: 2)");
  assert.match(text, /owned by Ben Bauman \(actor id: 2\)/);
});

test("item detail names an unknown owner actor by its id", async () => {
  const { ownerFact, text } = await renderOwner({
    owner_actor_id: 9, owner_name: null,
    owner_label: "unknown actor (actor id: 9)",
  });
  assert.equal(ownerFact, "unknown actor (actor id: 9)");
  assert.match(text, /owned by unknown actor \(actor id: 9\)/);
});

test("item detail shows an unowned item as unassigned", async () => {
  const { ownerFact, text } = await renderOwner({
    owner_actor_id: null, owner_name: null, owner_label: "unassigned",
  });
  assert.equal(ownerFact, "unassigned");
  assert.doesNotMatch(text, /owned by/);
});
