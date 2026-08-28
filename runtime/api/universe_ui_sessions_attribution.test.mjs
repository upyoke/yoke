// A card shows an item in its work position only when its session is doing
// it. These cases cover the boundary: a filing attribution stays visible
// while the item is unclaimed, and disappears the moment another live
// session picks it up.
import assert from "node:assert/strict";
import test from "node:test";

import {
  appendHoldings,
  focusAttribution,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions_holdings.js";
import {
  FakeDocument,
  byClass,
} from "./universe_ui_dom_test_support.mjs";


function filerRow(overrides = {}) {
  return {
    session_id: "filer-1",
    liveness: "active",
    current_item: "YOK-4102",
    current_item_project_id: 1,
    current_item_project_sequence: 4102,
    current_item_title: "Filed by the steering seat",
    current_item_status: "idea",
    owns_current_item: false,
    work_role: null,
    current_item_holder_session_id: null,
    holdings: { current: [], previous: [], previous_remainder: 0 },
    ...overrides,
  };
}


function bodyFor(row) {
  const documentNode = new FakeDocument();
  const body = documentNode.createElement("div");
  appendHoldings(documentNode, body, row);
  return body;
}


test("a filed item nobody holds stays on the card under its own label", () => {
  const row = filerRow();
  assert.equal(focusAttribution(row), "filed");
  const body = bodyFor(row);
  assert.deepEqual(
    byClass(body, "session-holdings-label").map((node) => node.textContent),
    ["Filed · unclaimed"],
  );
  assert.equal(byClass(body, "session-item-link")[0].textContent, "YOK-4102");
  assert.match(
    byClass(body, "session-attached")[0].title,
    /no session holds a work claim on it/,
  );
});


test("a filed item another live session holds leaves this card entirely", () => {
  // The observed defect: a steering seat filed the item, a launched worker
  // claimed it moments later, and the seat's card went on advertising it.
  const row = filerRow({ current_item_holder_session_id: "worker-9" });
  assert.equal(focusAttribution(row), null);
  const body = bodyFor(row);
  assert.equal(byClass(body, "session-attached").length, 0);
  assert.equal(byClass(body, "session-item-link").length, 0);
  assert.equal(
    byClass(body, "session-unassigned")[0].textContent,
    "Filed by the steering seat",
  );
});


test("a worktree lane on another session's item is untouched by the rule", () => {
  // A lane is real work on somebody else's item, so the holder naming that
  // other session must not take the lane row off this card.
  const row = filerRow({
    work_role: "implementation",
    current_item_holder_session_id: "worker-9",
  });
  assert.equal(focusAttribution(row), "lane");
  const body = bodyFor(row);
  assert.match(byClass(body, "session-attached")[0].title, /^worktree lane/);
  assert.deepEqual(
    byClass(body, "session-holdings-label").map((node) => node.textContent),
    ["Currently held"],
  );
});


test("the session's own claim outranks any holder reading", () => {
  const row = filerRow({
    owns_current_item: true,
    holdings: {
      current: [{
        holding_kind: "work_claim", target_kind: "item", target: "YOK-4102",
      }],
      previous: [],
      previous_remainder: 0,
    },
  });
  assert.equal(focusAttribution(row), "claim");
  const body = bodyFor(row);
  assert.equal(byClass(body, "session-lock")[0].textContent, "🔒");
  assert.equal(byClass(body, "session-attached").length, 0);
});


test("an ended session shows no attribution at all", () => {
  assert.equal(focusAttribution(filerRow({ liveness: "ended" })), null);
});
