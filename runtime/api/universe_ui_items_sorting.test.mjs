import assert from "node:assert/strict";
import test from "node:test";
import { createProjectSelection } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_project_selection.js";
import { loadScreenSelections, refreshScreenSort, saveScreenSelection } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_app_shell_support.js";
import { createRosterLoader } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_items_roster_loader.js";
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
    if (request.function === "ui_preferences.screen_selection.list") return { envelope: { success: true, result: { sorts: {} } } };
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

const ok = (result) => ({ status: 200, envelope: { success: true, result } });

test("initial roster reads restore saved sorting or default without writing either", async () => {
  for (const saved of [null, { column: "owner", direction: "asc" }]) {
    const document = new FakeDocument(), root = document.createElement("div");
    const requests = [];
    let writes = 0;
    const preferences = createProjectSelection(() => {}, null, () => { writes += 1; });
    preferences.seed("items", ["7"]);
    const context = itemContext(document, async (request) => {
      if (request.function === "ui_preferences.screen_selection.list") return ok({ sorts: saved ? { items: saved } : {} });
      requests.push(request);
      return ok({ rows: [], match_count: 0 });
    });
    context.screenPreferences = preferences;
    renderItemsView(context, root, ["7"]);
    await settle();
    const expected = saved || { column: "updated_at", direction: "desc" };
    assert.equal(requests[0].payload.sort_column, expected.column);
    assert.equal(requests[0].payload.sort_direction, expected.direction);
    const header = allNodes(root).find((n) => n.tagName === "TH" && n.getAttribute("aria-sort") !== "none");
    assert.equal(header.children[0].getAttribute("data-sort-column"), expected.column);
    assert.equal(header.getAttribute("aria-sort"), expected.direction === "asc" ? "ascending" : "descending");
    assert.equal(writes, 0);
    assert.deepEqual(preferences.selectionFor("items"), ["7"]);
  }
});

test("returning focus leaves the open roster unchanged; reopening reads the saved sort", async () => {
  const document = new FakeDocument(), controller = new AbortController();
  let stored = { column: "title", direction: "asc" };
  const requests = [];
  const preferences = createProjectSelection(() => {});
  preferences.seed("items", ["7"]);
  const context = itemContext(document, async (request) => {
    if (request.function === "ui_preferences.screen_selection.list") return ok({ sorts: { items: stored }, views: { items: { selection: "all" } } });
    requests.push(request);
    return ok({ rows: [], next_cursor: "next", match_count: 100 });
  });
  context.screenPreferences = preferences;
  context.signal = controller.signal;
  const loader = createRosterLoader({ context, scope: ["7"] });
  await loader.start();
  await loader.setFilter("workflow", "dash");
  await loader.loadMore();
  assert.equal(requests.at(-1).payload.cursor, "next");
  stored = { column: "title", direction: "desc" };
  const beforeFocus = requests.length;
  document.defaultView.dispatchEvent(new Event("focus"));
  document.visibilityState = "visible";
  document.dispatchEvent(new Event("visibilitychange"));
  await settle();
  assert.equal(requests.length, beforeFocus);
  assert.equal(requests.at(-1).payload.sort_direction, "asc");
  assert.equal(requests.at(-1).payload.workflow, "dash");
  assert.equal(requests.at(-1).payload.cursor, "next");
  assert.deepEqual(preferences.selectionFor("items"), ["7"]);
  await createRosterLoader({ context, scope: ["7"] }).start();
  assert.equal(requests.at(-1).payload.sort_direction, "desc");
  controller.abort();
  const count = requests.length;
  document.defaultView.dispatchEvent(new Event("focus"));
  await settle();
  assert.equal(requests.length, count);
  assert.equal(document.defaultView.listenerCounts.get("focus") || 0, 0);
});

test("a late refresh cannot replace a newer local choice or swallow its save failure", async () => {
  let finishRead;
  const preferences = createProjectSelection(() => {}, null, () => Promise.reject(new Error("offline")));
  preferences.markReady(true);
  const refresh = preferences.refreshSortFor("items", () => new Promise((resolve) => { finishRead = resolve; }));
  await settle();
  const saving = preferences.saveSortFor("items", { column: "title", direction: "asc" });
  finishRead({ sorts: { items: { column: "owner", direction: "desc" } } });
  await refresh;
  assert.match(await saving, /Click a column header to retry/);
  assert.deepEqual(preferences.sortFor("items"), { column: "title", direction: "asc" });
});

test("refresh waits for local saves and failed reads preserve order with visible recovery", async () => {
  let finishSave;
  const preferences = createProjectSelection(() => {}, null, () => new Promise((resolve) => { finishSave = resolve; }));
  preferences.markReady(true);
  const saving = preferences.saveSortFor("items", { column: "title", direction: "asc" });
  let reads = 0;
  const refresh = preferences.refreshSortFor("items", async () => { reads += 1; throw new Error("offline"); });
  await settle();
  assert.equal(reads, 0);
  finishSave();
  await saving;
  assert.match(await refresh, /last known order.*reload to retry/);
  const document = new FakeDocument(), root = document.createElement("div");
  const context = itemContext(document, async (request) => {
    if (request.function === "ui_preferences.screen_selection.list") return { envelope: { success: false } };
    assert.equal(request.payload.sort_column, "title");
    return ok({ rows: [], match_count: 0 });
  });
  context.screenPreferences = preferences;
  renderItemsView(context, root, "all");
  await settle();
  assert.match(byClass(root, "error-banner")[0].textContent, /Saved sorting could not be loaded/);
});

test("an older view's refresh cannot overwrite a newer refresh that found no saved choice", async () => {
  const preferences = createProjectSelection(() => {});
  let finishOld;
  const old = preferences.refreshSortFor("items", () => new Promise((resolve) => { finishOld = resolve; }));
  await settle();
  await preferences.refreshSortFor("items", async () => ({ sorts: {} }));
  finishOld({ sorts: { items: { column: "title", direction: "asc" } } });
  await old;
  assert.deepEqual(preferences.sortFor("items"), { column: "updated_at", direction: "desc" });
});
