import assert from "node:assert/strict";
import test from "node:test";

import { renderItemDetailView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_items.js";
import { FakeDocument, allNodes, byClass, settle } from "./universe_ui_dom_test_support.mjs";
import { detailItem, itemContext, itemText } from "./universe_ui_items_test_support.mjs";

async function renderLevel(level, override = level?.override) {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const item = detailItem("dash");
  item.level = level;
  item.workflow.item_posture.level = override;
  renderItemDetailView(itemContext(documentNode, async () => ({
    status: 200, envelope: { success: true, result: { item } },
  })), root, String(item.project.id), item.public_ref);
  await settle();
  const rows = allNodes(byClass(root, "item-facts")[0]);
  const row = rows.find((node) => node.tagName === "TR" && node.children[0].textContent === "Level");
  const posture = byClass(root, "item-posture-grid")[0];
  assert.ok(!byClass(posture, "item-posture-label").some((node) => node.textContent === "Level"));
  assert.doesNotMatch(itemText(posture), /Well-specified edits/);
  return { root, row, rows };
}

const override = { shift: -1, max: "SENIOR", reason: "Well-specified edits" };
const senior = { level: "SENIOR", glyph: "🦉", stage_level: "SENIOR", stage_glyph: "🦉", stage_id: "implementing" };

for (const [name, level] of [
  ["absent level data", undefined],
  ["terminal level data", null],
  ["empty level data", {}],
  ["missing stage default", { level: "SENIOR", override }],
  ["missing effective level", { stage_level: "SENIOR", override }],
  ["matching default without override", senior],
  ["matching default with empty override", { ...senior, override: {} }],
  ["fixed bounds matching default", { ...senior, override: { min: "SENIOR", max: "SENIOR", reason: "launch-time level" } }],
  ["maximum matching default", { ...senior, override: { max: "SENIOR", reason: "limit" } }],
  ["shift clamped to default", { ...senior, override: { shift: -1, min: "SENIOR", reason: "floor" } }],
  ["higher shift clamped to default", { ...senior, override: { shift: 1, max: "SENIOR", reason: "ceiling" } }],
  ["different stage with matching default", { ...senior, level: "JUNIOR", stage_level: "JUNIOR", override }],
]) {
  test(`item details omit Level for ${name}`, async () => {
    const { row } = await renderLevel(level, override);
    assert.equal(row, undefined);
  });
}

for (const [name, level, expected] of [
  ["lower effective level", { ...senior, level: "JUNIOR", glyph: "🐥", override },
    "Default: 🦉 SENIOR Override: 🐥 JUNIOR shift -1 · max SENIOR · Well-specified edits"],
  ["higher effective level from another stage", { ...senior, stage_level: "JUNIOR", stage_glyph: "🐥", override: { min: "SENIOR", reason: "Stronger review" } },
    "Default: 🐥 JUNIOR Override: 🦉 SENIOR min SENIOR · Stronger review"],
  ["difference without override detail", { ...senior, level: "JUNIOR", glyph: "🐥" },
    "Default: 🦉 SENIOR Override: 🐥 JUNIOR"],
  ["difference without glyphs", { level: "JUNIOR", stage_level: "SENIOR" },
    "Default: SENIOR Override: JUNIOR"],
]) {
  test(`item details label default and override for ${name}`, async () => {
    const { row, rows } = await renderLevel(level);
    const labels = rows.filter((node) => node.tagName === "TH").map((node) => node.textContent);
    assert.equal(labels[labels.indexOf("Status") + 1], "Level");
    assert.equal(itemText(row.children[1]), expected);
    assert.equal(byClass(row, "item-inline")[0].children[1].tagName, "B");
  });
}
