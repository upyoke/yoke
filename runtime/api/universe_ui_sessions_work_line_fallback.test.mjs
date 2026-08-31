// The work line under a session card is a fallback for a session holding
// nothing, not a verdict on sessions whose duty is shaped some other way.
// A steering seat drives its lanes through claims the steering block above
// states, so the holdings list renders none of them — and the card used to
// answer that emptiness by declaring there was no actionable work.
import assert from "node:assert/strict";
import test from "node:test";

import {
  appendHoldings,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions_holdings.js";
import {
  FakeDocument,
  byClass,
} from "./universe_ui_dom_test_support.mjs";


function row(holdings, overrides = {}) {
  return {
    session_id: "session-1",
    liveness: "active",
    current_item: null,
    current_item_title: null,
    owns_current_item: false,
    work_role: null,
    current_item_holder_session_id: null,
    holdings: { current: [], previous: [], previous_remainder: 0, ...holdings },
    ...overrides,
  };
}


function bodyFor(sessionRow, projects = []) {
  const documentNode = new FakeDocument();
  const body = documentNode.createElement("div");
  appendHoldings(documentNode, body, sessionRow, projects);
  return body;
}


function fallbackText(body) {
  return byClass(body, "session-unassigned").map((node) => node.textContent);
}


test("a steering seat's card carries no fallback line", () => {
  // The steering block above states the seat, so the holdings list renders
  // nothing — which is not the same as the seat holding nothing.
  const body = bodyFor(row({
    current: [{
      holding_kind: "work_claim",
      target_kind: "steering",
      target: "yoke",
      project_id: 1,
      strategy_docs: ["MASTER-PLAN"],
    }],
  }), [{ id: 1, slug: "yoke" }]);

  assert.deepEqual(fallbackText(body), []);
});


test("a lease or document lock alone carries no fallback line", () => {
  const body = bodyFor(row({
    current: [
      {
        holding_kind: "coordination",
        target_kind: "migration_serialization",
        target: "LIVE_DB_MIGRATION:governed_migration_module",
      },
      {
        holding_kind: "strategy_document",
        target_kind: "strategy_document",
        target: "MASTER-PLAN",
        project_id: 1,
        strategy_doc: "MASTER-PLAN",
      },
    ],
  }));

  assert.deepEqual(fallbackText(body), []);
  assert.equal(byClass(body, "session-holdings-group").length, 1);
});


test("an item claim still puts the item title on the card", () => {
  const body = bodyFor(row(
    {
      current: [{
        holding_kind: "work_claim",
        target_kind: "item",
        target: "YOK-4200",
        item_ref: "YOK-4200",
        item_project_id: 1,
        item_project_sequence: 4200,
      }],
    },
    {
      current_item: "YOK-4200",
      current_item_project_id: 1,
      current_item_project_sequence: 4200,
      current_item_title: "Ship the typed workflow",
      owns_current_item: true,
    },
  ));

  assert.deepEqual(fallbackText(body), []);
  assert.equal(
    byClass(body, "session-item-title")[0].textContent,
    "Ship the typed workflow",
  );
});


test("a session holding nothing states that fact and nothing more", () => {
  const body = bodyFor(row({}));

  assert.deepEqual(fallbackText(body), ["No active work claims"]);
});
