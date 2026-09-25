import assert from "node:assert/strict";
import test from "node:test";

import { renderActorsView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_actors.js";
import { FakeDocument, allNodes } from "./universe_ui_dom_test_support.mjs";

function actor(status, tokens = []) {
  return {
    id: 2, kind: "human", name: "Member", status, tokens,
    roles: { org: [{ org: "Test", role: "member" }], projects: [] },
    identity: { email: "member@example.test" },
  };
}

function fixture(rosters) {
  const document = new FakeDocument();
  const main = document.createElement("main");
  const calls = [];
  const context = {
    document, capabilities: { portability_mode: "hosted" },
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

test("Actors shows disabled state and nonsecret key metadata, then refreshes after enable", async () => {
  const initial = {
    current_actor_id: 1, can_manage_actors: true,
    rows: [actor("disabled", [{
      token_id: 42, name: "machine", last_used_at: "never",
      machine_id: "machine-a", machine_name: "Office",
    }])],
  };
  const refreshed = {
    current_actor_id: 1, can_manage_actors: true,
    rows: [actor("active")],
  };
  const { context, main, calls } = fixture([initial, refreshed]);
  await renderActorsView(context, main);
  assert.match(main.textContent, /disabled/);
  assert.match(main.textContent, /machine \(#42\)/);
  assert.match(main.textContent, /Office/);
  assert.match(main.textContent, /Sign in again and reconnect affected machines/);
  const enable = allNodes(main).find((node) => node.tagName === "BUTTON" && node.textContent === "Enable");
  assert.ok(enable);
  enable.dispatchEvent(new Event("click"));
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(calls[1], {
    function: "actors.state.set", payload: { actor_id: 2, enabled: true },
  });
  assert.equal(calls[2].function, "actors.roster");
  assert.match(main.textContent, /No active keys/);
  assert.match(main.textContent, /active/);
});

test("Actors renders an empty roster without stale controls", async () => {
  const { context, main } = fixture([{
    current_actor_id: 1, can_manage_actors: false, rows: [],
  }]);
  await renderActorsView(context, main);
  assert.match(main.textContent, /No actors are registered/);
  assert.equal(allNodes(main).filter((node) => node.tagName === "BUTTON").length, 0);
});
