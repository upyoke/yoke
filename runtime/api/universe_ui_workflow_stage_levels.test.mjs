import assert from "node:assert/strict";
import test from "node:test";
import { byClass } from "./universe_ui_dom_test_support.mjs";
import { classText, mountWorkflows, workflowFixture, workflowsClient } from "./universe_ui_workflows_test_support.mjs";

test("stage cards show served level glyphs beneath checks and omit terminal levels", async (t) => {
  const workflow = workflowFixture({ stages: [
    { id: "draft", label: "Drafted", gates: [], level: "SENIOR" },
    { id: "prove", label: "Proving", gates: [{ id: "evidence_check" }], level: "JUNIOR" },
    { id: "ship", label: "Shipped", gates: [] },
  ] });
  workflow.level_glyphs = { SENIOR: "🦉", JUNIOR: "🐥" };
  const { root } = await mountWorkflows(t, workflowsClient([workflow]));
  assert.deepEqual(classText(root, "workflow-stage-level"), ["🦉 SENIOR", "🐥 JUNIOR"]);
  const cards = byClass(root, "workflow-stage");
  assert.deepEqual(cards[1].children.map((node) => node.textContent), ["Proving", "1 check", "🐥 JUNIOR"]);
  assert.equal(byClass(cards[2], "workflow-stage-level").length, 0);
});

