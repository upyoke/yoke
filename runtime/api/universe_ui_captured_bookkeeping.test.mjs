import assert from "node:assert/strict";
import test from "node:test";

import {
  renderItemDetailView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_items.js";
import {
  FakeDocument,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  detailItem,
  itemContext,
  itemText,
} from "./universe_ui_items_test_support.mjs";

test("captured without artifacts is bookkeeping, not proof", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const item = detailItem("dash");
  item.qa_plan_attachments = [];
  item.qa_requirements = [{
    id: 9,
    run_id: 44,
    qa_kind: "browser-inspection",
    qa_phase: "verification",
    requirement_source: "welcome-frame",
    plan_case_key: "welcome-frame",
    method_id: "browser-inspection",
    method_name: "Browser inspection",
    verdict: null,
    outcome: null,
    case_outcome: null,
    execution_status: "captured",
    capture_degraded_reason: null,
    artifacts: [],
    proof_summary: "",
  }];

  renderItemDetailView(itemContext(documentNode, async (request) => ({
    status: 200,
    envelope: {
      success: true,
      result: request.function === "items.detail.get"
        ? { item }
        : {
          execution: {
            execution_document: {
              slug: "WORKFLOW-TYPES",
              parent_slug: "MASTER-PLAN",
            },
          },
        },
    },
  })), root, "7", "ACM-22");
  await settle();

  const rendered = itemText(root);
  assert.match(rendered, /capture-stage bookkeeping/);
  assert.match(rendered, /0 artifacts/);
  assert.match(rendered, /This run attached no artifacts/);
  const pills = byClass(root, "item-proof-row").map(
    (row) => byClass(row, "pill")[0]?.textContent,
  );
  assert.equal(pills[0], "captured (no artifacts)");
});
