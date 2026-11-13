import assert from "node:assert/strict";
import test from "node:test";

import { sessionCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import { steeringHoldingText } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions_steering.js";
import { compactStrategyDocuments } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions_holdings_disclosure.js";
import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";

function steering(project) {
  return {
    holding_kind: "work_claim", target_kind: "steering", project_id: 7,
    project, scope: { project_id: 7, document: null }, strategy_docs: [],
    released_at: "2026-11-01T12:00:00Z",
  };
}

for (const executor of ["claude", "codex", "cursor"]) {
  test(`${executor} card names a retired project in released steering holdings`, () => {
    const node = sessionCard(new FakeDocument(), {
      session_id: "retired-project-holder", executor, liveness: "active",
      mode: "wait", claims: [], activity_at: "2026-11-01T12:00:00Z",
      holdings: { current: [], previous: [steering("retired-project")] },
      messageability: { messageable: false },
    }, () => {}, []);
    const text = byClass(node, "session-hold-target").map((row) => row.textContent).join(" ");
    assert.match(text, /retired-project/);
    assert.doesNotMatch(text, /unknown project/);
  });
}

test("steering names prefer holding facts and tolerate older servers", () => {
  const projects = [{ id: 7, slug: "roster-name" }];
  assert.match(steeringHoldingText(steering("retired-project"), projects), /retired-project/);
  assert.match(steeringHoldingText(steering(undefined), projects), /roster-name/);
  assert.match(steeringHoldingText(steering(undefined), []), /unknown project/);
});

test("strategy document groups prefer their project slug with an older-server fallback", () => {
  const entries = ["MISSION", "VISION"].map((strategy_doc) => ({
    holding_kind: "strategy_document", project_id: 7,
    project: "retired-project", strategy_doc,
  }));
  const projects = [{ id: 7, slug: "roster-name" }];
  assert.equal(compactStrategyDocuments(entries, [])[0].project, "retired-project");
  assert.equal(compactStrategyDocuments(entries, projects)[0].project, "retired-project");
  assert.equal(compactStrategyDocuments(entries.map(({ project, ...row }) => row), projects)[0].project, "roster-name");
});
