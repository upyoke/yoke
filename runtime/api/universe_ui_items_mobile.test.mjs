import assert from "node:assert/strict";
import test from "node:test";
import { itemTable } from "../../packages/yoke-core/src/yoke_core/ui/static/item_roster_table.js";
import { createPathNavigation } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_path_navigation.js";
import { FakeDocument, allNodes, byClass } from "./universe_ui_dom_test_support.mjs";

const fixture = {
  public_ref: ["DEMO", 7].join("-"), project_id: 1, project_slug: "demo",
  title: "Preserve context across a narrow viewport", workflow_id: "dash",
  status: "implementing", owner: "A named owner",
  claimed_by: { actor_label: "A separate claimant" },
  updated_at: "2026-01-01T12:00:00Z",
};

for (const scope of [["1"], ["1", "2"]]) {
  test(`narrow item cards keep correct value labels for ${scope.length} projects`, () => {
    const document = new FakeDocument();
    const root = itemTable(document, [fixture], () => "/items/example", scope,
      [{ id: 1, slug: "demo" }], { column: "updated_at", direction: "desc" }, () => {}, () => {});
    assert.equal(byClass(root, "table-stacks-narrow").length, 1);
    const row = byClass(root, "item-roster-row")[0];
    const cells = Object.fromEntries(row.children.map((cell) => [cell.getAttribute("data-label"), cell]));
    assert.equal(cells.ID.textContent, fixture.public_ref);
    assert.equal(cells.Title.textContent, fixture.title);
    assert.equal(cells.Status.textContent, "implementing");
    assert.equal(cells.Owner.textContent, fixture.owner);
    assert.match(cells["Claimed by"].textContent, /A separate claimant/);
    assert.equal(cells["Claimed by"].children.length, 1);
    assert.equal(allNodes(cells["Last updated"]).some((node) => node.tagName === "TIME"), true);
    assert.equal(Boolean(cells.project), scope.length > 1);
  });
}

test("card headers preserve all existing sort actions and row navigation", () => {
  const document = new FakeDocument(), sorted = [];
  const root = itemTable(document, [fixture], () => "/items/example", ["1"], [],
    { column: "updated_at", direction: "desc" }, (key) => sorted.push(key),
    createPathNavigation(document.defaultView).navigate);
  const header = byClass(root, "item-roster-sort")[0];
  assert.equal(byClass(header, "item-sort-button").length, 7);
  for (const button of byClass(header, "item-sort-button")) button.dispatchEvent(new Event("click"));
  assert.deepEqual(sorted, ["id", "title", "workflow", "status", "owner", "claimed_by", "updated_at"]);
  byClass(root, "item-roster-row")[0].dispatchEvent(new Event("click"));
  assert.equal(document.defaultView.location.href, "/items/example");
});
