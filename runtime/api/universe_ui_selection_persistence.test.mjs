import assert from "node:assert/strict";
import test from "node:test";
import { mountUniverseApp, withProjectSelection } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { createProjectSelection, resolveProjectSelection } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_project_selection.js";
import { navEntry, scopeForEntry } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_navigation.js";
import { FakeDocument, allNodes, byClass, response, settle } from "./universe_ui_dom_test_support.mjs";
import { createSelectionNavigation, selectionRoute } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_selection_routes.js";
import { itemsCalls, scopeChips, twoProjectClient } from "./universe_ui_read_views_test_support.mjs";

const projects = [{ id: 1 }, { id: 2 }, { id: 3 }];

// A client double whose `ui_preferences.screen_selection.*` pair is backed
// by a plain object instead of a real server — the same object passed to a
// second `preferenceClient(...)` call simulates the SAME actor's state
// surviving a reload, remount, or second tab; a fresh call with no
// argument simulates a different actor with nothing saved yet.
function preferenceClient(initialViews = {}) {
  const base = twoProjectClient();
  const state = { views: { ...initialViews } };
  return {
    requests: base.requests,
    state,
    async call(request) {
      if (request.function === "ui_preferences.screen_selection.list") {
        base.requests.push(request);
        return { status: 200, envelope: { success: true, result: { views: state.views } } };
      }
      if (request.function === "ui_preferences.screen_selection.set") {
        base.requests.push(request);
        state.views = {
          ...state.views,
          [request.payload.view_id]: {
            selection: request.payload.selection, focus: request.payload.focus,
          },
        };
        return { status: 200, envelope: { success: true, result: {} } };
      }
      return base.call(request);
    },
  };
}

test("removed IDs are purged from both selection and focus", () => {
  const state = createProjectSelection(null);
  state.setFocusFor("items", "3");
  resolveProjectSelection(state, "items", projects, ["1", "3"]);
  resolveProjectSelection(state, "items", projects.slice(0, 2));
  assert.deepEqual(state.selectionFor("items"), ["1"]);
  assert.equal(state.focusFor("items"), null);
  resolveProjectSelection(state, "items", [], null);
  assert.equal(state.selectionFor("items"), "all");
});

test("explicit invalid and All deep links override remembered scope; absent scope preserves it", () => {
  const state = createProjectSelection(null);
  const entry = navEntry("items");
  assert.deepEqual(scopeForEntry(entry, "2", projects, state), ["2"]);
  // No explicit route scope: this view's own remembered selection persists.
  assert.deepEqual(scopeForEntry(entry, null, projects, state), ["2"]);
  assert.equal(scopeForEntry(entry, "removed", projects, state), "all");
  scopeForEntry(entry, "1,2", projects, state);
  assert.equal(scopeForEntry(entry, "all", projects, state), "all");
});

test("each view's remembered selection and focus are independent of every other view", () => {
  const state = createProjectSelection(null);
  scopeForEntry(navEntry("items"), "1,2", projects, state);
  // Architecture (single-scope) has never been visited: its own default
  // selection is "all", so its candidate fallback is the whole roster —
  // never Items' pair.
  assert.equal(scopeForEntry(navEntry("architecture"), null, projects, state), "1");
  assert.equal(scopeForEntry(navEntry("architecture"), "3", projects, state), "3");
  assert.deepEqual(state.selectionFor("items"), ["1", "2"]);
  // A scope-none view touches neither.
  assert.equal(scopeForEntry(navEntry("workflows"), null, projects, state), null);
  assert.deepEqual(state.selectionFor("items"), ["1", "2"]);
  assert.equal(state.focusFor("architecture"), "3");
  // Github is its own independent multi-view: it never inherits Items'
  // selection.
  assert.deepEqual(scopeForEntry(navEntry("github"), null, projects, state), "all");
});

test("ordinary detail, focus, global, and workflow links carry each view's own remembered scope", () => {
  const state = createProjectSelection(null);
  state.seed("items", ["1", "2"]);
  assert.equal(withProjectSelection("#/items/42?project=2", state),
    "#/items/42?project=2&selection=1,2");
  state.seed("architecture", "all");
  assert.equal(withProjectSelection("#/architecture?project=2", state),
    "#/architecture?project=2&selection=all");
  state.seed("github", "all");
  assert.equal(withProjectSelection("#/github?project=2", state), "#/github?project=2");
  state.seed("workflows", ["2"]);
  assert.equal(withProjectSelection("#/workflows/dash", state), "#/workflows/dash?selection=2");
  state.seed("organization", ["1", "2"]);
  assert.equal(withProjectSelection("#/organization", state), "#/organization?project=1,2");
  state.seed("items", ["1"]);
  assert.equal(withProjectSelection("#/items?project=all", state), "#/items?project=all");
  assert.equal(withProjectSelection("#/items/42?project=2&selection=all", state),
    "#/items/42?project=2&selection=all");
});

test("a failed persistence write surfaces a notice; the in-memory value stays usable", async () => {
  const state = createProjectSelection(() => Promise.reject(new Error("network down")));
  state.markReady();
  assert.deepEqual(resolveProjectSelection(state, "items", projects, "2"), ["2"]);
  await settle();
  assert.match(state.notice, /could not be saved/);
  assert.deepEqual(state.selectionFor("items"), ["2"]);
});

test("before the initial read settles, normalization never persists a default over the server's real value", async () => {
  const saved = [];
  const state = createProjectSelection((viewId) => {
    saved.push(viewId);
    return Promise.resolve({ envelope: { success: true } });
  });
  // Never marked ready: as far as this module knows, the initial read is
  // still unknown, so no write may leave this process yet.
  assert.deepEqual(resolveProjectSelection(state, "items", projects, "2"), ["2"]);
  await settle();
  assert.deepEqual(saved, []);
  state.markReady();
  assert.deepEqual(resolveProjectSelection(state, "items", projects, "3"), ["3"]);
  await settle();
  assert.deepEqual(saved, ["items"]);
});

test("late-rendered and retained host anchors track their own view's selection, including copied detail links", () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  root.querySelectorAll = () => allNodes(root).filter((node) => node.tagName === "A");
  let observeChanges, disconnected = false;
  documentNode.defaultView.MutationObserver = class {
    constructor(callback) { observeChanges = callback; }
    observe() {}
    disconnect() { disconnected = true; }
  };
  const state = createProjectSelection(null);
  state.seed("strategy", ["1", "2"]);
  const navigation = createSelectionNavigation(root, documentNode.defaultView, state);
  const anchor = documentNode.createElement("a");
  anchor.setAttribute("href", "#/strategy/PLAN?project=2");
  root.appendChild(anchor);
  observeChanges([{ type: "childList", addedNodes: [anchor] }]);
  assert.equal(anchor.getAttribute("href"), "#/strategy/PLAN?project=2&selection=1,2");
  state.setSelectionFor("strategy", "all");
  navigation.refresh();
  assert.equal(anchor.getAttribute("href"), "#/strategy/PLAN?project=2&selection=all");
  // Workflows has never been touched, so navigating there uses its own
  // default — never Strategy's remembered value.
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
  const state = createProjectSelection(null);
  state.seed("items", ["1", "2"]);
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
  const state = createProjectSelection(null);
  state.seed("items", ["1", "2"]);
  assert.equal(selectionRoute({ view: "items", detail: "new" }, state, null,
    "#/items/new?workflow=dash&return=workflows"),
  "#/items/new?workflow=dash&return=workflows&selection=1,2");
});

async function mountAt(t, hash, client = preferenceClient()) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  const windowNode = documentNode.defaultView;
  windowNode.location.hash = hash;
  const replacements = [];
  windowNode.history = { replaceState(_state, _title, route) {
    replacements.push(route);
    windowNode.location.hash = route;
  } };
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
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

test("each screen's own remembered selection renders in its own chip state and survives the round trip", async (t) => {
  const client = preferenceClient();
  const { root, windowNode, navigate } = await mountAt(t, "#/items?project=1,2", client);
  assert.deepEqual(selected(root), ["ALP", "BET"]);

  await navigate("#/workflows");
  // Workflows has never been touched: it starts at its own default, never
  // Items' remembered pair.
  assert.deepEqual(selected(root), ["All"]);
  assert.equal(windowNode.location.hash, "#/workflows?project=all");
  assert.match(byClass(root, "scope-context-note")[0].textContent, /universe-wide/);

  await navigate("#/items");
  // Items' own selection survived the round trip untouched.
  assert.deepEqual(selected(root), ["ALP", "BET"]);
  assert.deepEqual(itemsCalls(client).at(-1).payload.projects, ["1", "2"]);

  await navigate("#/projects");
  assert.deepEqual(selected(root), ["All"]);
  assert.equal(windowNode.location.hash, "#/projects?project=all");
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

test("reload and host remount restore each view's own saved selection; a fresh actor starts independently", async (t) => {
  const client = preferenceClient();
  const first = await mountAt(t, "#/items?project=1,2", client);
  assert.deepEqual(client.state.views.items?.selection, ["1", "2"]);
  first.mounted.unmount();

  // Same server-backed state (the same actor, a reload or a second tab),
  // same view: the remembered selection survives.
  const next = await mountAt(t, "#/items", client);
  assert.deepEqual(selected(next.root), ["ALP", "BET"]);
  next.mounted.unmount();

  // Events was never touched, even under the same persisted state: it
  // starts at its own default rather than inheriting Items' pair.
  const events = await mountAt(t, "#/events", client);
  assert.deepEqual(selected(events.root), ["All"]);
  events.mounted.unmount();

  // A fresh actor — a client with nothing saved yet — starts independently.
  const other = await mountAt(t, "#/items", preferenceClient());
  assert.deepEqual(selected(other.root), ["All"]);
});

test("a denied save resolves normally but still surfaces the notice through the real app wiring", async (t) => {
  const client = preferenceClient();
  const baseCall = client.call.bind(client);
  client.call = async (request) => {
    if (request.function === "ui_preferences.screen_selection.set") {
      client.requests.push(request);
      return {
        status: 200,
        envelope: { success: false, error: { code: "actor_required", message: "no bound actor" } },
      };
    }
    return baseCall(request);
  };
  const { root, navigate } = await mountAt(t, "#/items", client);
  // One navigation, one settle — no second navigation to force a repaint.
  // The failed (but resolved, never rejected) save must trigger its own
  // re-render once it settles; if that wiring regresses, this fails instead
  // of a second navigation quietly masking the missing repaint.
  await navigate("#/items?project=2");
  assert.match(byClass(root, "scope-context-note")[0].textContent, /could not be saved/);
});

test("an unsuccessful initial read never lets a default clobber the server's real value", async (t) => {
  const client = preferenceClient({ items: { selection: ["1"], focus: null } });
  const baseCall = client.call.bind(client);
  let listCalls = 0;
  client.call = async (request) => {
    if (request.function === "ui_preferences.screen_selection.list") {
      listCalls += 1;
      client.requests.push(request);
      return {
        status: 200,
        envelope: { success: false, error: { code: "unavailable", message: "down" } },
      };
    }
    return baseCall(request);
  };
  // The route names a project that differs from what the server actually
  // holds for Items — normally this would persist as the new value.
  const { root } = await mountAt(t, "#/items?project=2", client);
  assert.equal(listCalls, 1);
  // The failed read never marked this mount ready, so the mismatch was
  // never written back over the actor's real saved selection.
  assert.deepEqual(client.state.views.items, { selection: ["1"], focus: null });
  // The person still sees that their choices are not being saved this
  // session, on the very first render — no extra navigation needed.
  assert.match(byClass(root, "scope-context-note")[0].textContent,
    /Couldn't load saved projects/);
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
