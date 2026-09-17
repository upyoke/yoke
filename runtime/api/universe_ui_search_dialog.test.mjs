// Universe search: what it searches, what it says when it cannot, and what it
// shows before anyone has typed. The dialog is the feature — the header field
// is only one of its two entry points — so these drive it the way an operator
// does: open it, read the empty state, type, and follow a result.

import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  SEARCH_DEBOUNCE_MS,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_shell_controls.js";
import {
  FakeDocument, byClass, response, settle, visibleText,
} from "./universe_ui_dom_test_support.mjs";

async function settleSearch() {
  await new Promise((resolve) => setTimeout(resolve, SEARCH_DEBOUNCE_MS + 20));
  await settle();
}

function ok(result) {
  return { status: 200, envelope: { success: true, result } };
}

function refused() {
  return {
    status: 403,
    envelope: { success: false, error: { message: "function_not_allowed" } },
  };
}

// Two projects, because the point of the scope rule is that neither the
// selector nor the project a result belongs to narrows the search.
const PROJECTS = [
  { id: 1, slug: "yoke", name: "Yoke", public_item_prefix: "YOK" },
  { id: 3, slug: "platform", name: "Platform", public_item_prefix: "PLAT" },
];

function fixtureClient({ overrides = {}, calls = [] } = {}) {
  const answers = {
    "organizations.get": () => ok({ name: "Yoke" }),
    "projects.list": () => ok({ rows: PROJECTS }),
    "items.overview.list": () => ok({ rows: [] }),
    "items.search.run": () => ok({ matches: [{
      id: "YOK-2228", internal_id: 2262, title: "Rebaseline the workbench",
      project_id: 1, project: "yoke", status: "implementing",
    }] }),
    "sessions.list": (payload) => (payload?.session_id ? ok({ rows: [] }) : ok({
      rows: [{
        session_id: "session-rebaseline", project_id: 1, project: "yoke",
        current_item: "YOK-2228", executor: "codex",
      }],
    })),
    "strategy.doc.list": (payload, target) => ok({
      docs: String(target?.project_id) === "3"
        ? [{ slug: "REBASELINE-PLAN", title: "Rebaseline plan", state: "active" }]
        : [],
    }),
    "qa.plan.list": (payload) => ok({
      rows: String(payload?.project) === "1"
        ? [{ id: 298, slug: "rebaseline-review", name: "Rebaseline review" }]
        : [],
    }),
    "events.query.run": (payload) => ok({
      rows: payload?.event_name ? [] : [{
        event_name: "RebaselineRecorded", project_id: 1,
        created_at: "2026-09-17T04:00:00Z", source_type: "engine",
      }],
    }),
    "packs.list": (payload) => ok({
      packs: String(payload?.project) === "1"
        ? [{ slug: "rebaseline-pack", name: "Rebaseline Pack" }]
        : [],
    }),
    "ui_preferences.search_history.list": () => ok({ queries: [] }),
    "ui_preferences.search_history.record": () => ok({ queries: [] }),
  };
  return {
    async call(request) {
      calls.push(request);
      const answer = overrides[request.function] || answers[request.function];
      if (!answer) throw new Error(`unexpected function ${request.function}`);
      return answer(request.payload, request.target);
    },
  };
}

async function mountShell(t, client) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.body = documentNode.createElement("body");
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  t.after(() => mounted.unmount());
  return { documentNode, root };
}

test("the dialog opens on what search covers, not on invented results", async (t) => {
  const calls = [];
  const client = fixtureClient({
    calls,
    overrides: {
      "ui_preferences.search_history.list": () => ok({
        queries: ["YOK-2228", "release-readiness"],
      }),
    },
  });
  const { documentNode, root } = await mountShell(t, client);

  const overlay = byClass(root, "header-search-overlay")[0];
  assert.equal(overlay.hidden, true);
  byClass(root, "header-search")[0].dispatchEvent(new Event("click"));
  await settle();
  assert.equal(overlay.hidden, false);
  assert.equal(
    documentNode.activeElement, byClass(root, "header-search-input")[0],
  );

  // Every domain the dialog advertises, in the order results arrive in.
  assert.deepEqual(
    byClass(root, "header-search-chip").map((node) => node.textContent),
    ["Items", "Sessions", "Strategy docs", "QA plans", "Events", "Packs"],
  );
  // The scope rule is stated where the operator is deciding what to type.
  const hint = byClass(root, "header-search-hint")[0].textContent;
  assert.match(hint, /project selector does not narrow it/);
  assert.match(hint, /which project it is in/);

  // Recent is this actor's own stored history, read from the control plane.
  assert.deepEqual(
    byClass(root, "header-search-row").map((node) => node.textContent),
    ["YOK-2228", "release-readiness"],
  );
  assert.ok(calls.some(
    (call) => call.function === "ui_preferences.search_history.list",
  ));
  // Nothing was searched, so nothing claims to have matched.
  assert.equal(byClass(root, "header-search-result").length, 0);
});

test("a query reaches all six domains across every project", async (t) => {
  const calls = [];
  const { root } = await mountShell(t, fixtureClient({ calls }));
  byClass(root, "header-search")[0].dispatchEvent(new Event("click"));
  const input = byClass(root, "header-search-input")[0];
  input.value = "rebaseline";
  input.dispatchEvent(new Event("input"));
  await settleSearch();

  const groups = byClass(root, "header-search-section-label")
    .map((node) => node.textContent);
  assert.deepEqual(groups, [
    "Items", "Sessions", "Strategy docs", "QA plans", "Events", "Packs",
  ]);
  const results = byClass(root, "header-search-result");
  assert.deepEqual(results.map((node) => node.href), [
    "#/items/2228?project=1",
    "#/sessions/session-rebaseline?project=1",
    // The strategy doc lives in the OTHER project and is found anyway.
    "#/strategy/REBASELINE-PLAN?project=3",
    "#/qa-plans/298?project=1",
    "#/events?project=1",
    "#/packs",
  ]);
  // Each result says which project it is in, because scope never narrowed.
  assert.match(byClass(root, "header-search-meta")[2].textContent, /platform/);

  // A project-scoped read is asked of every project, never of the selection.
  const packProjects = calls
    .filter((call) => call.function === "packs.list")
    .map((call) => call.payload.project);
  assert.deepEqual(packProjects.sort(), ["1", "3"]);
  const docProjects = calls
    .filter((call) => call.function === "strategy.doc.list")
    .map((call) => call.target.project_id);
  assert.deepEqual(docProjects.sort(), ["1", "3"]);

  // Searching something that matched is what gets remembered.
  const recorded = calls.find(
    (call) => call.function === "ui_preferences.search_history.record",
  );
  assert.deepEqual(recorded.payload, { query: "rebaseline" });
});

test("a domain that refused is named rather than read as empty", async (t) => {
  const { root } = await mountShell(t, fixtureClient({
    overrides: { "packs.list": () => refused() },
  }));
  byClass(root, "header-search")[0].dispatchEvent(new Event("click"));
  const input = byClass(root, "header-search-input")[0];
  input.value = "rebaseline";
  input.dispatchEvent(new Event("input"));
  await settleSearch();

  assert.equal(byClass(root, "header-search-section-label").length, 5);
  const hints = byClass(root, "header-search-hint").map((n) => n.textContent);
  assert.match(hints.at(-1), /Could not search Packs/);
  assert.match(hints.at(-1), /missing, not absent/);
});

test("a query that matches nothing says so without blaming the index", async (t) => {
  const empty = () => ok({ matches: [], rows: [], docs: [], packs: [] });
  const { root } = await mountShell(t, fixtureClient({
    overrides: {
      "items.search.run": empty,
      "sessions.list": empty,
      "strategy.doc.list": empty,
      "qa.plan.list": empty,
      "events.query.run": empty,
      "packs.list": empty,
    },
  }));
  byClass(root, "header-search")[0].dispatchEvent(new Event("click"));
  const input = byClass(root, "header-search-input")[0];
  input.value = "nothing-here";
  input.dispatchEvent(new Event("input"));
  await settleSearch();

  assert.match(
    byClass(root, "header-search-status")[0].textContent,
    /Nothing matches “nothing-here”/,
  );
  assert.equal(byClass(root, "header-search-result").length, 0);
});

test("one character is not a query", async (t) => {
  const calls = [];
  const { root } = await mountShell(t, fixtureClient({ calls }));
  byClass(root, "header-search")[0].dispatchEvent(new Event("click"));
  const input = byClass(root, "header-search-input")[0];
  input.value = "r";
  input.dispatchEvent(new Event("input"));
  await settleSearch();

  assert.match(
    byClass(root, "header-search-status")[0].textContent,
    /at least 2 characters/,
  );
  assert.equal(
    calls.filter((call) => call.function === "items.search.run").length, 0,
  );
});

test("the shortcut opens and closes the same dialog from anywhere", async (t) => {
  const { documentNode, root } = await mountShell(t, fixtureClient());
  const overlay = byClass(root, "header-search-overlay")[0];
  const shortcut = () => {
    const event = new Event("keydown");
    Object.defineProperties(event, {
      key: { value: "k" }, metaKey: { value: true }, ctrlKey: { value: false },
    });
    documentNode.defaultView.dispatchEvent(event);
  };
  shortcut();
  await settle();
  assert.equal(overlay.hidden, false);
  shortcut();
  assert.equal(overlay.hidden, true);

  // Escape is the way out wherever focus sits: a modal owns the whole page
  // while it is open, so its dismissal is window-level too.
  shortcut();
  await settle();
  const escape = new Event("keydown");
  Object.defineProperty(escape, "key", { value: "Escape" });
  documentNode.defaultView.dispatchEvent(escape);
  assert.equal(overlay.hidden, true);
});

test("arrow keys walk the results and Enter follows the active one", async (t) => {
  const { documentNode, root } = await mountShell(t, fixtureClient());
  byClass(root, "header-search-button")[0].dispatchEvent(new Event("click"));
  const input = byClass(root, "header-search-input")[0];
  input.value = "rebaseline";
  input.dispatchEvent(new Event("input"));
  await settleSearch();

  const key = (name) => {
    const event = new Event("keydown");
    Object.defineProperty(event, "key", { value: name });
    input.dispatchEvent(event);
  };
  key("ArrowDown");
  key("ArrowDown");
  const results = byClass(root, "header-search-result");
  assert.equal(results[1].classList.contains("active"), true);
  assert.equal(
    input.getAttribute("aria-activedescendant"), results[1].id,
  );
  key("Enter");
  assert.equal(
    documentNode.defaultView.location.hash,
    "#/sessions/session-rebaseline?project=1",
  );
  assert.equal(byClass(root, "header-search-overlay")[0].hidden, true);
});

test("a recent query re-runs it rather than only filling the field", async (t) => {
  const { root } = await mountShell(t, fixtureClient({
    overrides: {
      "ui_preferences.search_history.list": () => ok({
        queries: ["rebaseline"],
      }),
    },
  }));
  byClass(root, "header-search")[0].dispatchEvent(new Event("click"));
  await settle();
  byClass(root, "header-search-row")[0].dispatchEvent(new Event("click"));
  await settle();

  assert.equal(byClass(root, "header-search-input")[0].value, "rebaseline");
  assert.ok(visibleText(byClass(root, "header-search-body")[0])
    .includes("Rebaseline the workbench"));
});
