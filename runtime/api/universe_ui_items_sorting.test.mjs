import assert from "node:assert/strict";
import test from "node:test";
import { createProjectSelection } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_project_selection.js";
import { loadScreenSelections, saveScreenSelection } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_app_shell_support.js";
import { renderItemsView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_items.js";
import { FakeDocument, allNodes, byClass, settle } from "./universe_ui_dom_test_support.mjs";
import { itemContext, itemText } from "./universe_ui_items_test_support.mjs";

test("column sorting resets paging and saves a separate actor preference", async () => {
  const document = new FakeDocument(), root = document.createElement("div");
  const requests = [], saved = [];
  const preferences = createProjectSelection(() => {}, null, (view, sort) => { saved.push({ view, sort }); });
  preferences.seed("items", ["7"]);
  preferences.markReady(true);
  const context = itemContext(document, async (request) => {
    requests.push(request);
    return { status: 200, envelope: { success: true, result: {
      rows: [{ public_ref: "ACM-1", project_id: 7, title: "A row", workflow_id: "dash", status: "idea", updated_at: new Date(Date.now() - 300000).toISOString() }],
      next_cursor: "next", match_count: 2,
    } } };
  });
  context.screenPreferences = preferences;
  renderItemsView(context, root, ["7"]);
  await settle();
  assert.equal(requests[0].payload.sort_column, "updated_at");
  assert.equal(requests[0].payload.sort_direction, "desc");
  assert.match(itemText(root), /5m ago/);
  const click = () => byClass(root, "item-sort-button").find((n) => n.attributes.get("data-sort-column") === "title").dispatchEvent(new Event("click"));
  click(); await settle();
  assert.equal(requests.at(-1).payload.sort_column, "title");
  assert.equal(requests.at(-1).payload.sort_direction, "asc");
  assert.equal("cursor" in requests.at(-1).payload, false);
  click(); await settle();
  assert.equal(requests.at(-1).payload.sort_direction, "desc");
  assert.equal(saved.at(-1).sort.direction, "desc");
  assert.deepEqual(preferences.selectionFor("items"), ["7"]);
  assert.equal(allNodes(root).filter((n) => n.tagName === "TH").find((n) => n.attributes.get("aria-sort") === "descending").children[0].attributes.get("data-sort-column"), "title");
});

test("server sort restoration and failure reporting preserve project selection", async () => {
  const preferences = createProjectSelection(() => {}, null, () => Promise.reject(new Error("offline")));
  await loadScreenSelections({ call: async () => ({ status: 200, envelope: { success: true, result: {
    views: { items: { selection: ["7"], focus: null } }, sorts: { items: { column: "owner", direction: "asc" } },
  } } }) }, preferences);
  assert.deepEqual(preferences.sortFor("items"), { column: "owner", direction: "asc" });
  assert.match(await preferences.saveSortFor("items", { column: "title", direction: "asc" }), /Click a column header to retry/);
  assert.deepEqual(preferences.selectionFor("items"), ["7"]);
  let payload;
  await saveScreenSelection({ call: async (request) => { payload = request.payload; return { envelope: { success: true } }; } }, "items", null, null, { column: "title", direction: "asc" });
  assert.deepEqual(payload, { view_id: "items", sort: { column: "title", direction: "asc" } });
});


test("a server without sort support never receives a sort write that could overwrite scope", async () => {
  let saves = 0;
  const preferences = createProjectSelection(() => {}, null, () => { saves += 1; });
  await loadScreenSelections({ call: async () => ({ envelope: { success: true, result: { views: { items: { selection: ["7"] } } } } }) }, preferences);
  assert.match(await preferences.saveSortFor("items", { column: "title", direction: "asc" }), /Update the server/);
  assert.equal(saves, 0);
  assert.deepEqual(preferences.selectionFor("items"), ["7"]);
});
