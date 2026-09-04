import assert from "node:assert/strict";
import test from "node:test";

import { renderWorkflowItemDetail } from "../../packages/yoke-core/src/yoke_core/ui/static/item_view_details.js";
import { renderItemsView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_items.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  detailItem,
  itemContext,
  itemText,
} from "./universe_ui_items_test_support.mjs";


test("Task detail is laneless and omits merge and QA affordances", () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const item = detailItem("task");

  renderWorkflowItemDetail(itemContext(documentNode, async () => null), root, item);

  const rendered = itemText(root);
  assert.match(rendered, /Instruction/);
  assert.match(rendered, /no git lane/);
  assert.match(rendered, /\/yoke advance ACM-22/);
  assert.doesNotMatch(rendered, /Verification|merge SHA|worktree branch/);
  const facts = allNodes(byClass(root, "item-facts")[0])
    .filter((node) => node.tagName === "TH")
    .map((node) => node.textContent);
  assert.ok(!facts.includes("Worktree"));
});


test("Task roster rows suppress stale QA attention", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const context = itemContext(documentNode, async () => ({
    status: 200,
    envelope: {
      success: true,
      result: {
        count: 1,
        rows: [{
          public_ref: "ACM-30", project_id: 7, title: "Refresh inventory",
          workflow_id: "task", status: "idea", stage_label: "Idea",
          owner: "Rae", claimed_by: null,
          qa_attention: {
            verdict: "undetermined",
            verdict_reason: "Stale QA projection",
          },
        }],
      },
    },
  }));

  renderItemsView(context, root, ["7"]);
  await settle();

  assert.match(itemText(root), /Refresh inventory/);
  assert.match(itemText(root), /task/);
  assert.doesNotMatch(itemText(root), /QA undetermined|Stale QA projection/);
});
