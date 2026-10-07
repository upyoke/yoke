import assert from "node:assert/strict";
import test from "node:test";

import { renderActorsView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_actors.js";
import { FakeDocument, allNodes, byClass } from "./universe_ui_dom_test_support.mjs";

function actor(status, tokens = [], overrides = {}) {
  return {
    id: 2, kind: "human", name: "Member", status, tokens,
    roles: { org: [{ org: "Test", role: "member" }], projects: [] },
    identity: { email: "member@example.test" },
    ...overrides,
  };
}

function preferences(saved = null) {
  const saves = [];
  let sort = saved;
  return {
    saves,
    sortFor: (viewId) => (viewId === "actors" ? sort : null),
    refreshSortFor: async () => "",
    saveSortFor: (viewId, chosen) => { saves.push([viewId, chosen]); sort = chosen; return Promise.resolve(""); },
  };
}

function fixture(rosters, screenPreferences) {
  const document = new FakeDocument();
  const main = document.createElement("main");
  const calls = [];
  const context = {
    document, capabilities: { portability_mode: "hosted" }, screenPreferences,
    isMounted: () => true,
    client: {
      async call(request) {
        calls.push(request);
        const result = request.function === "actors.roster"
          ? rosters.shift() : { actor_id: 2, status: "active", revoked_tokens: 0 };
        return { status: 200, envelope: { success: true, result } };
      },
    },
  };
  return { context, main, calls };
}

const button = (main, text) => allNodes(main).find((node) => node.tagName === "BUTTON" && node.textContent === text);
const names = (main) => byClass(main, "actors-name").map((node) => node.textContent);
const settle = () => new Promise((resolve) => setImmediate(resolve));

test("disabled actors are hidden behind a counted toggle that survives an enable", async () => {
  const initial = {
    current_actor_id: 1, can_manage_actors: true,
    rows: [actor("disabled", [{
      token_id: 42, name: "machine", last_used_at: "never",
      machine_id: "machine-a", machine_name: "Office",
    }]), actor("active", [], { id: 3, name: "Other" })],
  };
  const refreshed = {
    current_actor_id: 1, can_manage_actors: true,
    rows: [actor("active"), actor("active", [], { id: 3, name: "Other" })],
  };
  const { context, main, calls } = fixture([initial, refreshed]);
  await renderActorsView(context, main);
  assert.deepEqual(names(main), ["Other"]);
  assert.match(main.textContent, /Show disabled \(1\)/);
  const toggle = allNodes(main).find((node) => node.tagName === "INPUT" && node.type === "checkbox");
  assert.equal(toggle.checked, false);
  toggle.checked = true;
  toggle.dispatchEvent(new Event("change"));
  assert.deepEqual(names(main), ["Member", "Other"]);
  assert.match(main.textContent, /machine \(#42\)/);
  assert.match(main.textContent, /Office/);
  assert.doesNotMatch(main.textContent, /reconnect affected machines/);
  button(main, "Enable").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(calls[1], {
    function: "actors.state.set", payload: { actor_id: 2, enabled: true },
  });
  assert.equal(calls[2].function, "actors.roster");
  assert.deepEqual(names(main), ["Member", "Other"]);
  assert.doesNotMatch(main.textContent, /Show disabled/);
});

test("Actors renders an empty roster without stale controls", async () => {
  const { context, main } = fixture([{
    current_actor_id: 1, can_manage_actors: false, rows: [],
  }]);
  await renderActorsView(context, main);
  assert.match(main.textContent, /No actors are registered/);
  assert.equal(allNodes(main).filter((node) => node.tagName === "BUTTON").length, 0);
});

test("disabling names the actor and requires confirmation, with cancel and retry", async () => {
  const roster = { current_actor_id: 1, can_manage_actors: true, rows: [actor("active")] };
  const { context, main, calls } = fixture([roster, roster]);
  const original = context.client.call;
  let attempts = 0;
  context.client.call = async (request) => {
    if (request.function === "actors.state.set" && ++attempts === 1) {
      return { status: 503, envelope: { success: false, error: { message: "Unavailable" } } };
    }
    return original(request);
  };
  await renderActorsView(context, main);
  button(main, "Disable").dispatchEvent(new Event("click"));
  assert.match(main.textContent, /Disable Member\? Their API keys will be revoked\./);
  assert.equal(attempts, 0);
  button(main, "Cancel").dispatchEvent(new Event("click"));
  assert.equal(attempts, 0);
  button(main, "Disable").dispatchEvent(new Event("click"));
  button(main, "Disable Member").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(button(main, "Disable Member").disabled, false);
  assert.match(main.textContent, /Unavailable/);
  button(main, "Disable Member").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(attempts, 2);
  assert.deepEqual(calls.find((call) => call.function === "actors.state.set").payload, { actor_id: 2, enabled: false });
});

test("columns sort through the shared header and save under the actors screen", async () => {
  const roster = {
    current_actor_id: 1, can_manage_actors: false,
    rows: [
      actor("active", [], { id: 4, name: "beta", identity: { email: "a@example.test" } }),
      actor("active", [], { id: 5, name: "Alpha", identity: { email: "z@example.test" } }),
    ],
  };
  const saved = preferences({ column: "email", direction: "desc" });
  const { context, main } = fixture([roster], saved);
  await renderActorsView(context, main);
  assert.deepEqual(names(main), ["Alpha", "beta"]);
  const actorSort = () => allNodes(main).find((node) => node.getAttribute?.("data-sort-column") === "name");
  actorSort().dispatchEvent(new Event("click"));
  assert.deepEqual(names(main), ["Alpha", "beta"]);
  assert.deepEqual(saved.saves, [["actors", { column: "name", direction: "asc" }]]);
  actorSort().dispatchEvent(new Event("click"));
  assert.deepEqual(names(main), ["beta", "Alpha"]);
  assert.deepEqual(saved.saves[1], ["actors", { column: "name", direction: "desc" }]);
});

test("a server that does not save the actors sort keeps the header sort without a retry prompt", async () => {
  const { createProjectSelection } = await import("../../packages/yoke-core/src/yoke_core/ui/static/universe_project_selection.js");
  const writes = [];
  const store = createProjectSelection(() => {}, null, (viewId, sort) => { writes.push([viewId, sort]); });
  const olderServer = async () => ({ views: {}, sorts: { items: { column: "title", direction: "asc" } } });
  assert.equal(await store.refreshSortFor("actors", olderServer), "");
  const roster = {
    current_actor_id: 1, can_manage_actors: false,
    rows: [actor("active", [], { id: 4, name: "beta" }), actor("active", [], { id: 5, name: "Alpha" })],
  };
  const { context, main } = fixture([roster], store);
  context.client.call = async (request) => ({
    status: 200, envelope: { success: true, result: request.function === "actors.roster" ? roster : await olderServer() },
  });
  await renderActorsView(context, main);
  allNodes(main).find((node) => node.getAttribute?.("data-sort-column") === "name").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(names(main), ["beta", "Alpha"]);
  assert.deepEqual(writes, []);
  assert.match(main.textContent, /does not save this page's sort; it applies until you leave the page/);
  assert.doesNotMatch(main.textContent, /retry/);
});
