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

test("Blitz detail route renders the full execution-document composition", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const requests = [];
  const blitz = detailItem("blitz");
  blitz.workflow.policies.file_budget = "required";
  blitz.workflow.policies.path_claims = "required";
  blitz.worktrees.push({
    branch: "codex/footer-proof",
    lane_role: "worker",
    state: "committed",
  });
  renderItemDetailView(itemContext(documentNode, async (request) => {
    requests.push(request);
    if (request.function === "items.detail.get") {
      return {
        status: 200,
        envelope: {
          success: true,
          result: { item: blitz },
        },
      };
    }
    if (request.function === "strategy.execution.get") {
      return {
        status: 200,
        envelope: {
          success: true,
          result: {
            execution: {
              execution_document: {
                slug: "WORKFLOW-TYPES",
                parent_slug: "MASTER-PLAN",
                updated_at: "2026-07-26T11:00:00Z",
                execution_claim: { owner_kind: "item", owner_item_id: 51 },
              },
            },
          },
        },
      };
    }
    throw new Error(`unexpected function ${request.function}`);
  }), root, "7", "ACM-22");
  await settle();

  assert.deepEqual(
    requests.map((request) => request.function),
    ["items.detail.get", "strategy.execution.get"],
  );
  const rendered = itemText(root);
  assert.match(rendered, /Execution document/);
  assert.match(rendered, /WORKFLOW-TYPES/);
  assert.match(rendered, /child of MASTER-PLAN/);
  assert.match(rendered, /Technical plan/);
  assert.match(rendered, /Touch the footer renderer first/);
  assert.match(rendered, /Progress Log/);
  assert.match(rendered, /Real values landed/);
  assert.match(rendered, /Worktree lanes · 2/);
  assert.match(rendered, /codex\/footer/);
  assert.match(rendered, /Verification/);
  assert.match(rendered, /Item details/);
  assert.match(rendered, /Live claim/);
  assert.match(rendered, /File budget\s+none · workflow default/);
  assert.match(rendered, /Path claims\s+none · workflow default/);
  assert.match(rendered, /Child items none/);
  assert.match(rendered, /Parallelism 2 lanes/);
  assert.match(rendered, /Integration main session/);
  assert.match(rendered, /Migrations governed/);
  assert.match(rendered, /\/yoke blitz ACM-22/);
  assert.doesNotMatch(rendered, /Build one shell/);
  assert.doesNotMatch(rendered, /Overall narrative/);
  assert.deepEqual(
    byClass(root, "item-posture-label").map((node) => node.textContent),
    [
      "Child items", "File Budget", "Path survey", "Path claims",
      "Parallelism", "Integration", "Migrations",
    ],
  );
  assert.deepEqual(
    byClass(root, "item-posture-value").map((node) => node.textContent),
    [
      "none", "optional", "on", "optional", "2 lanes", "main session",
      "governed",
    ],
  );
  const lanePills = byClass(root, "pill").filter(
    (node) => ["active", "committed"].includes(
      node.attributes.get("data-state"),
    ),
  );
  assert.deepEqual(
    lanePills.map((node) => [node.className, node.textContent]),
    [["pill run", "active"], ["pill good", "slice committed"]],
  );
  const facts = byClass(root, "item-facts")[0];
  assert.deepEqual(
    byClass(facts, "item-workflow").map((node) => node.textContent),
    ["blitz"],
  );
  assert.equal(byClass(facts, "row-link").length, 0);
});

test("Blitz parallelism states actual singular and absent lanes", async () => {
  const renderParallelism = async (worktrees) => {
    const documentNode = new FakeDocument();
    const root = documentNode.createElement("div");
    const blitz = detailItem("blitz");
    blitz.worktrees = worktrees;
    renderItemDetailView(itemContext(documentNode, async (request) => {
      if (request.function === "items.detail.get") {
        return {
          status: 200,
          envelope: { success: true, result: { item: blitz } },
        };
      }
      return {
        status: 200,
        envelope: {
          success: true,
          result: { execution: { execution_document: null } },
        },
      };
    }), root, "7", "ACM-22");
    await settle();
    return itemText(root);
  };

  const oneLane = detailItem("blitz").worktrees;
  assert.match(await renderParallelism(oneLane), /Parallelism 1 lane/);
  assert.match(await renderParallelism([]), /Parallelism no worker lanes/);
});

test("Blitz detail exposes an execution-document read failure", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const requests = [];
  renderItemDetailView(itemContext(documentNode, async (request) => {
    requests.push(request);
    if (request.function === "items.detail.get") {
      return {
        status: 200,
        envelope: {
          success: true,
          result: { item: detailItem("blitz") },
        },
      };
    }
    return {
      status: 502,
      envelope: {
        success: false,
        error: { message: "execution relationship unavailable" },
      },
    };
  }), root, "7", "ACM-22");
  await settle();

  assert.deepEqual(
    requests.map((request) => request.function),
    ["items.detail.get", "strategy.execution.get"],
  );
  assert.match(itemText(root), /execution relationship unavailable/);
  assert.equal(byClass(root, "blitz-document").length, 0);
});
