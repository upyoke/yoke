import assert from "node:assert/strict";
import test from "node:test";

import {
  renderItemDetailView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_items.js";
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

test("Epic detail reports task completion and its narrower fact spine", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const epic = detailItem("epic");
  epic.qa_plan_attachments[0].materialized_count = 0;
  renderItemDetailView(itemContext(documentNode, async (request) => {
    if (request.function === "items.detail.get") {
      return {
        status: 200,
        envelope: {
          success: true,
          result: { item: epic },
        },
      };
    }
    if (request.function === "epic_tasks.list.run") {
      return {
        status: 200,
        envelope: {
          success: true,
          result: {
            tasks: [
              { task_num: 1, title: "Build shell", status: "done" },
              { task_num: 2, title: "Verify shell", status: "planned" },
            ],
          },
        },
      };
    }
    throw new Error(`unexpected function ${request.function}`);
  }), root, "7", "ACM-22");
  await settle();

  const rendered = itemText(root);
  assert.match(rendered, /Tasks · 2 1 of 2 done/);
  assert.match(rendered, /Shepherd log/);
  assert.match(rendered, /Ready to execute/);
  assert.match(rendered, /Worktree plan/);
  assert.match(rendered, /intent · lanes activate per task at conduct/);
  assert.match(
    rendered,
    /project default · plus per-task attachments · materializes per case/,
  );
  assert.match(
    rendered,
    /project default · materializes one requirement per case at release/,
  );
  assert.match(rendered, /\/yoke conduct ACM-22/);
  const labels = allNodes(byClass(root, "item-facts")[0])
    .filter((node) => node.tagName === "TH")
    .map((node) => node.textContent);
  assert.deepEqual(labels, [
    "Project", "Workflow", "Status", "Owner", "Created",
  ]);
  assert.equal(
    byClass(byClass(root, "item-facts")[0], "row-link")[0].href,
    "#/workflows/epic",
  );
  assert.deepEqual(
    byClass(root, "item-posture-label").map((node) => node.textContent),
    ["Path claims", "Worktrees", "Parallelism", "Migrations"],
  );
  assert.deepEqual(
    byClass(root, "item-posture-value").map((node) => node.textContent),
    ["required · per task", "worker + integration", "task graph", "governed"],
  );
});

for (const workflowId of ["issue", "dash"]) {
  test(`${workflowId} detail renders its prototype-specific spine from the read model`, async () => {
    const documentNode = new FakeDocument();
    const root = documentNode.createElement("div");
    const requests = [];
    renderItemDetailView(itemContext(documentNode, async (request) => {
      requests.push(request);
      return {
        status: 200,
        envelope: {
          success: true,
          result: { item: detailItem(workflowId) },
        },
      };
    }), root, "7", "ACM-22");
    await settle();

    assert.deepEqual(requests[0], {
      function: "items.detail.get",
      payload: {},
      target: {
        kind: "item",
        item_ref: "ACM-22",
        project_id: "7",
      },
    });
    const rendered = itemText(root);
    assert.match(rendered, workflowId === "dash" ? /Instruction/ : /Spec/);
    assert.match(rendered, /Item details/);
    assert.match(rendered, /Verification/);
    assert.match(rendered, /Execution posture/);
    assert.match(rendered, /Run in a harness/);
    assert.match(
      rendered,
      /browser-close → reviewing-implementation/,
    );
    assert.match(
      rendered,
      /project default ·\s+materialized .*one requirement per case/,
    );
    assert.match(rendered, /e2e-suite → release/);
    assert.match(
      rendered,
      /not materialized yet — expands one requirement per case at release/,
    );
    assert.deepEqual(
      byClass(root, "item-proof-plan").map((node) => node.href),
      [
        "#/qa/plans/3?project=7",
        "#/qa/plans/4?project=7",
      ],
    );
    assert.match(
      rendered,
      workflowId === "dash" ? /ad hoc · footer-renders/ : /responsive-footer/,
    );
    assert.match(
      rendered,
      workflowId === "dash"
        ? /Browser inspection — screenshot the footer; the agent confirms the typo is gone and the links still render/
        : /1 screenshot/,
    );
    assert.doesNotMatch(
      rendered,
      /The footer stays visible at both breakpoints/,
    );
    assert.match(rendered, /codex\/footer/);
    assert.match(
      rendered,
      workflowId === "issue"
        ? /\/yoke polish ACM-22/
        : /\/yoke dash ACM-22/,
    );
    if (workflowId === "issue") {
      assert.match(rendered, /Acceptance criteria/);
      assert.match(rendered, /Focus stays put/);
      assert.match(rendered, /File budget\s+1 file/);
      assert.match(rendered, /is this item proven\? one place/);
      assert.match(rendered, /Progress Log/);
      assert.equal(byClass(root, "rich-check").length, 1);
    }
    assert.equal(
      allNodes(root).some((node) => node.tagName === "PRE"),
      false,
    );
    assert.ok(allNodes(root).some((node) => node.tagName === "TIME"));
    assert.ok(allNodes(root).some(
      (node) => node.attributes.get("data-state") ===
        "reviewing-implementation",
    ));
    assert.deepEqual(
      byClass(root, "item-posture-label").map((node) => node.textContent),
      workflowId === "dash"
        ? ["Child items", "Path claims", "Worktrees", "Migrations"]
        : ["Path claims", "Worktrees", "Parallelism", "Migrations"],
    );
    assert.deepEqual(
      byClass(root, "item-posture-value").map((node) => node.textContent),
      workflowId === "dash"
        ? ["none", "optional", "one", "governed"]
        : [
          "required · file budget", "one lane", "inside item", "governed",
        ],
    );
    assert.deepEqual(
      allNodes(byClass(root, "item-facts")[0])
        .filter((node) => node.tagName === "TH")
        .map((node) => node.textContent),
      workflowId === "dash"
        ? [
          "Project", "Workflow", "Status", "Owner", "Claim",
          "Path claims", "Worktree", "Created",
        ]
        : [
          "Project", "Workflow", "Status", "Owner", "Claim",
          "File budget", "Worktree", "Created",
        ],
    );
    assert.equal(
      byClass(byClass(root, "item-facts")[0], "row-link")[0].href,
      `#/workflows/${workflowId}`,
    );
    assert.equal(
      byClass(root, "item-proof-row")[0].href,
      workflowId === "dash"
        ? "#/qa/methods/browser-inspection?project=7"
        : "#/qa/activity?project=7",
    );
    assert.equal(
      byClass(byClass(root, "item-proof-row")[0], "pill")[0].textContent,
      workflowId === "dash" ? "review" : "needs review",
    );
  });
}

test("promoted Dash detail links back to its source field note", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const dash = detailItem("dash");
  dash.source_field_note = {
    entry_id: 22890,
    category: "field-note-observation",
    context: "curate",
    project_id: 7,
  };
  renderItemDetailView(itemContext(documentNode, async (request) => ({
    status: 200,
    envelope: {
      success: true,
      result: { item: dash },
    },
  })), root, "7", "ACM-22");
  await settle();

  assert.match(itemText(root), /Promoted from field note/);
  assert.match(itemText(root), /Open field note #22890/);
  assert.equal(
    byClass(root, "item-action").find(
      (node) => node.textContent === "Open field note #22890",
    ).href,
    "#/ouroboros/22890?project=7",
  );
});
