import assert from "node:assert/strict";
import test from "node:test";
import { mountUniverseApp, withProjectSelection } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { createProjectSelection, resolveProjectSelection } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_project_selection.js";
import { navEntry, scopeForEntry } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_navigation.js";
import { FakeDocument, allNodes, byClass, response, settle } from "./universe_ui_dom_test_support.mjs";
import { createSelectionNavigation, selectionRoute } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_selection_routes.js";
import { itemsCalls, scopeChips, twoProjectClient } from "./universe_ui_read_views_test_support.mjs";

const projects = [{ id: 1 }, { id: 2 }, { id: 3 }];
const identity = { universeId: "universe-a", actorId: "actor-a" };
function storageWindow() {
  const entries = new Map();
  return { localStorage: {
    getItem: (key) => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, value),
  } };
}

test("All, one, and multiple survive remount without crossing actor/universe boundaries", () => {
  const windowNode = storageWindow();
  for (const selection of ["all", ["2"], ["1", "3"]]) {
    const state = createProjectSelection(windowNode, identity);
    resolveProjectSelection(state, projects, selection);
    assert.deepEqual(createProjectSelection(windowNode, identity).selection, selection);
    for (const other of [{ ...identity, actorId: "b" }, { ...identity, universeId: "b" }]) {
      assert.equal(createProjectSelection(windowNode, other).selection, "all");
    }
  }
  assert.equal(createProjectSelection(windowNode).selection, "all");
});

test("removed IDs are purged from both selection and focus before persistence", () => {
  const windowNode = storageWindow();
  const state = createProjectSelection(windowNode, identity);
  state.focus = "3";
  resolveProjectSelection(state, projects, ["1", "3"]);
  resolveProjectSelection(state, projects.slice(0, 2));
  assert.deepEqual(state.selection, ["1"]);
  assert.equal(state.focus, null);
  assert.deepEqual(createProjectSelection(windowNode, identity).selection, ["1"]);
  resolveProjectSelection(state, [], null);
  assert.equal(state.selection, "all");
});

test("explicit invalid and All deep links override remembered scope; absent scope preserves it", () => {
  const state = createProjectSelection({});
  const entry = navEntry("items");
  assert.deepEqual(scopeForEntry(entry, "2", projects, state), ["2"]);
  assert.deepEqual(scopeForEntry(navEntry("events"), null, projects, state), ["2"]);
  assert.equal(scopeForEntry(entry, "removed", projects, state), "all");
  scopeForEntry(entry, "1,2", projects, state);
  assert.equal(scopeForEntry(entry, "all", projects, state), "all");
});

test("single focus and global content do not replace remembered multi-selection", () => {
  const state = createProjectSelection({});
  scopeForEntry(navEntry("items"), "1,2", projects, state);
  assert.equal(scopeForEntry(navEntry("architecture"), null, projects, state), "1");
  assert.equal(
    scopeForEntry(navEntry("architecture"), "3", projects, state, "1,2"), "3",
  );
  assert.deepEqual(state.selection, ["1", "2"]);
  assert.equal(scopeForEntry(navEntry("workflows"), null, projects, state), null);
  assert.deepEqual(state.selection, ["1", "2"]);
  assert.equal(scopeForEntry(navEntry("architecture"), null, projects, state), "3");
  assert.deepEqual(
    scopeForEntry(navEntry("github"), null, projects, state), ["1", "2"],
  );
});

test("ordinary detail, focus, global, and workflow links carry remembered scope", () => {
  assert.equal(withProjectSelection("#/items/42?project=2", ["1", "2"]),
    "#/items/42?project=2&selection=1,2");
  assert.equal(withProjectSelection("#/architecture?project=2", "all"),
    "#/architecture?project=2&selection=all");
  assert.equal(withProjectSelection("#/github?project=2", "all"),
    "#/github?project=2");
  assert.equal(withProjectSelection("#/workflows/dash", ["2"]),
    "#/workflows/dash?selection=2");
  assert.equal(withProjectSelection("#/organization", ["1", "2"]),
    "#/organization?project=1,2");
  assert.equal(withProjectSelection("#/items?project=all", ["1"]), "#/items?project=all");
  assert.equal(withProjectSelection("#/items/42?project=2&selection=all", ["1"]),
    "#/items/42?project=2&selection=all");
});

test("unavailable browser storage teaches recovery while in-memory navigation works", () => {
  const windowNode = { get localStorage() { throw new Error("disabled"); } };
  const state = createProjectSelection(windowNode, identity);
  assert.match(state.notice, /Allow browser storage/);
  assert.deepEqual(resolveProjectSelection(state, projects, "2"), ["2"]);
  assert.throws(() => createProjectSelection(windowNode, { actorId: "a" }), /identity_invalid/);
});

test("late-rendered and retained host anchors track selection, including copied detail links", () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  root.querySelectorAll = () => allNodes(root).filter((node) => node.tagName === "A");
  let observeChanges, disconnected = false;
  documentNode.defaultView.MutationObserver = class {
    constructor(callback) { observeChanges = callback; }
    observe() {}
    disconnect() { disconnected = true; }
  };
  const state = createProjectSelection({});
  state.selection = ["1", "2"];
  const navigation = createSelectionNavigation(root, documentNode.defaultView, state);
  const anchor = documentNode.createElement("a");
  anchor.setAttribute("href", "#/strategy/PLAN?project=2");
  root.appendChild(anchor);
  observeChanges([{ type: "childList", addedNodes: [anchor] }]);
  assert.equal(anchor.getAttribute("href"), "#/strategy/PLAN?project=2&selection=1,2");
  state.selection = "all";
  navigation.refresh();
  assert.equal(anchor.getAttribute("href"), "#/strategy/PLAN?project=2&selection=all");
  navigation.navigate("#/workflows/dash");
  assert.equal(documentNode.defaultView.location.hash, "#/workflows/dash?selection=all");
  navigation.dispose();
  assert.equal(disconnected, true);
});

test("row pointer and keyboard navigation use the same selection as the row anchor", () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const handlers = {};
  root.addEventListener = (name, handler) => { handlers[name] = handler; };
  const state = createProjectSelection({});
  state.selection = ["1", "2"];
  const navigation = createSelectionNavigation(root, documentNode.defaultView, state);
  const row = documentNode.createElement("tr");
  row.setAttribute("role", "link");
  const link = documentNode.createElement("a");
  link.setAttribute("href", "#/items/42?project=2");
  row.appendChild(link);
  row.querySelector = () => link;
  root.appendChild(row);
  for (const type of ["click", "keydown"]) {
    let prevented = false, stopped = false;
    handlers[type]({ type, target: row, key: "Enter", button: 0,
      preventDefault() { prevented = true; }, stopPropagation() { stopped = true; } });
    assert.equal(documentNode.defaultView.location.hash, "#/items/42?project=2&selection=1,2");
    assert.ok(prevented && stopped);
  }
  navigation.dispose();
});

test("normalization and selection changes retain a view's own query fields", () => {
  const state = createProjectSelection({});
  state.selection = ["1", "2"];
  assert.equal(selectionRoute({ view: "items", detail: "new" }, state, null,
    "#/items/new?workflow=dash&return=workflows"),
  "#/items/new?workflow=dash&return=workflows&selection=1,2");
});

async function mountAt(t, hash, windowStorage = storageWindow(), actorIdentity = identity) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  const windowNode = documentNode.defaultView;
  windowNode.localStorage = windowStorage.localStorage;
  windowNode.location.hash = hash;
  const replacements = [];
  windowNode.history = { replaceState(_state, _title, route) {
    replacements.push(route);
    windowNode.location.hash = route;
  } };
  const root = documentNode.createElement("div");
  const client = twoProjectClient();
  const mounted = mountUniverseApp(root, { client, selectionIdentity: actorIdentity });
  t.after(() => mounted.unmount());
  await settle();
  async function navigate(route) {
    windowNode.location.hash = route;
    windowNode.dispatchEvent(new Event("hashchange"));
    await settle();
  }
  return { root, windowNode, mounted, client, navigate, replacements };
}

function selected(root) {
  return scopeChips(root).filter((chip) => chip.classList.contains("on"))
    .map((chip) => chip.textContent);
}

test("global-to-project-to-global round trips synchronize chips, URLs and reads", async (t) => {
  const { root, client, windowNode, navigate } = await mountAt(t, "#/items?project=1,2");
  await navigate("#/workflows");
  assert.deepEqual(selected(root), ["ALP", "BET"]);
  assert.equal(windowNode.location.hash, "#/workflows?project=1,2");
  assert.match(byClass(root, "scope-context-note")[0].textContent, /universe-wide/);
  await navigate("#/items");
  // The pair is one read naming both projects, not one read per member.
  assert.deepEqual(itemsCalls(client).at(-1).payload.projects, ["1", "2"]);
  await navigate("#/projects");
  assert.deepEqual(selected(root), ["ALP", "BET"]);
  assert.equal(windowNode.location.hash, "#/projects?project=1,2");
});

test("history restores explicit All and selection without adding history entries", async (t) => {
  const { root, windowNode, navigate, replacements } = await mountAt(t, "#/items");
  assert.equal(windowNode.location.hash, "#/items?project=all");
  await navigate("#/items?project=2");
  assert.deepEqual(selected(root), ["BET"]);
  await navigate("#/items?project=all");
  assert.deepEqual(selected(root), ["All"]);
  await navigate("#/items?project=2");
  assert.deepEqual(selected(root), ["BET"]);
  assert.deepEqual(replacements, ["#/items?project=all"]);
});

test("reload and host remount restore saved selection; actor/universe switches start independently", async (t) => {
  const storage = storageWindow();
  const first = await mountAt(t, "#/items?project=1,2", storage);
  first.mounted.unmount();
  const next = await mountAt(t, "#/events", storage);
  assert.deepEqual(selected(next.root), ["ALP", "BET"]);
  const other = await mountAt(t, "#/items", storage, { ...identity, actorId: "other" });
  assert.deepEqual(selected(other.root), ["All"]);
});

test("detail focus preserves multi-selection and inaccessible focus never reads another project", async (t) => {
  const { root, client, navigate } = await mountAt(t, "#/strategy/PLAN-1?project=1&selection=1,2");
  assert.deepEqual(selected(root), ["ALP", "BET"]);
  assert.equal(byClass(root, "breadcrumb-parent")[0].href, "#/strategy?project=1,2");
  const before = client.requests.length;
  await navigate("#/strategy/PLAN-1?project=removed&selection=1,2");
  assert.match(root.textContent, /Project unavailable/);
  assert.equal(client.requests.length, before);
});
