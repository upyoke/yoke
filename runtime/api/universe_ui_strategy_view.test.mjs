import assert from "node:assert/strict";
import test from "node:test";

import {
  renderStrategyDocDetailView,
  renderStrategyView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_strategy.js";
import {
  renderBlitzItemDetail,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_blitz.js";
import {
  FakeDocument,
  allNodes,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function text(root) {
  return allNodes(root).map((node) => node.textContent || "").join(" ");
}

function context(documentNode, client) {
  return {
    document: documentNode,
    client,
    isMounted: () => true,
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }],
  };
}

function strategyDocument() {
  return {
    slug: "WORKFLOW-TYPES",
    content: "# Purpose\n\nExecute the plan.\n\n## Decisions\n\n- Keep one authority.",
    updated_at: "2026-07-26T12:00:00Z",
    updated_by: "ben",
    bytes: 84,
    parent_slug: "MASTER-PLAN",
    references: ["MASTER-PLAN"],
    current_revision: 2,
    pending_review_count: 1,
    review_requests: [{ id: 7, status: "pending" }],
    execution_claim: {
      owning_item_id: 2001,
      item_ref: "YOK-2001",
    },
    revisions: [
      {
        revision: 2,
        source_operation: "ingest",
        byte_length: 84,
        content_sha256: "d0fdad55aa",
        created_at: "2026-07-26T12:00:00Z",
      },
      {
        revision: 1,
        source_operation: "create",
        byte_length: 16,
        content_sha256: "4dece4a3bb",
        created_at: "2026-07-26T11:00:00Z",
      },
    ],
  };
}

test("Strategy corpus matches the prototype hierarchy with real read facts", async () => {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const requests = [];
  const client = {
    async call(request) {
      requests.push(request);
      return {
        status: 200,
        envelope: {
          success: true,
          result: {
            docs: [{
              slug: "WORKFLOW-TYPES",
              title: "Workflow registry and QA",
              parent_slug: "MASTER-PLAN",
              updated_by: "ben",
              updated_at: "today",
              revisions: 2,
              recent_writes: 1,
              archived: false,
              execution_state: "claimed",
              execution_item_id: 2001,
              execution_item_ref: "YOK-2001",
            }],
            writes: [{ day: new Date().toISOString().slice(0, 10), writes: 1 }],
          },
        },
      };
    },
  };

  renderStrategyView(context(documentNode, client), main, ["1"]);
  await settle();

  const rendered = text(main);
  assert.match(rendered, /Review and approve here/);
  assert.match(rendered, /Strategy corpus\s+· scoped to yoke/);
  assert.match(rendered, /1 writes this week/);
  assert.match(rendered, /Purpose \/ ancestry/);
  assert.match(rendered, /child of\s+MASTER-PLAN/);
  assert.match(rendered, /claimed · YOK-2001/);
  assert.match(rendered, /Writes\s+last 120 days/);
  assert.match(rendered, /Strategy-doc writes 1 this week/);
  assert.equal(requests[0].function, "strategy.surface.list");
  assert.deepEqual(requests[0].target, {
    kind: "global", project_id: "1",
  });
});

test("Strategy detail exposes document, history, diff, restore, and review", async () => {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const requests = [];
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "strategy.surface.get") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              project_slug: "yoke",
              document: strategyDocument(),
            },
          },
        };
      }
      if (request.function === "strategy.revision.diff") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: { comparison: { diff: "+Keep one authority." } },
          },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };

  renderStrategyDocDetailView(
    context(documentNode, client), main, "1", "WORKFLOW-TYPES",
  );
  await settle();
  let rendered = text(main);
  assert.match(rendered, /State & actions/);
  assert.match(rendered, /Approve revision 2/);
  assert.match(rendered, /Author through a harness/);
  assert.match(rendered, /Purpose/);
  assert.doesNotMatch(rendered, /<h1>/);

  const history = allNodes(main).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "History",
  );
  history.dispatchEvent(new Event("click"));
  rendered = text(main);
  assert.match(rendered, /Revision history/);
  assert.match(rendered, /Restore creates revision 3/);

  const viewDiff = allNodes(main).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "View diff",
  );
  viewDiff.dispatchEvent(new Event("click"));
  await settle();
  assert.match(text(main), /\+Keep one authority/);
  const diffRequest = requests.find(
    (request) => request.function === "strategy.revision.diff",
  );
  assert.deepEqual(diffRequest.payload, {
    slug: "WORKFLOW-TYPES",
    from_revision: 1,
    to_revision: 2,
  });
});

test("Blitz detail is a thin system-fact shell around the live document", async () => {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const requests = [];
  const client = {
    async call(request) {
      requests.push(request);
      return {
        status: 200,
        envelope: {
          success: true,
          result: {
            execution: {
              execution_document: strategyDocument(),
            },
          },
        },
      };
    },
  };
  const item = {
    id: 2001,
    public_ref: "YOK-2001",
    title: "Execute WORKFLOW-TYPES",
    status: "implementing",
    owner: "ben",
    created_at: "2026-07-26T10:00:00Z",
    project: { id: 1, slug: "yoke", name: "Yoke" },
    workflow: {
      id: "blitz",
      name: "Blitz",
      version: 1,
      stage_label: "implementing",
      executor_id: "blitz",
      policies: {
        path_claims: "optional",
        worktrees: "worker_lanes_optional_integration",
        parallelism: "maximum_safe_slices",
        generated_children: "none",
        delivery: "continuous",
      },
    },
    claim: { session_id: "session-a", actor_label: "ben" },
    worktrees: [
      {
        lane_role: "integration",
        branch: "codex/workflow-types",
        state: "active",
      },
      {
        lane_role: "worker",
        branch: "codex/registry-schema",
        state: "active",
      },
    ],
    qa_requirements: [],
    narrative: { body: "THIS PLAN BODY MUST NOT BE COPIED" },
  };

  renderBlitzItemDetail(context(documentNode, client), main, item);
  await settle();

  const rendered = text(main);
  assert.match(rendered, /Execution document/);
  assert.match(rendered, /WORKFLOW-TYPES/);
  assert.match(rendered, /Worktree lanes/);
  assert.match(rendered, /codex\/registry-schema/);
  assert.match(rendered, /Path claims none · workflow default/);
  assert.match(rendered, /Child items none/);
  assert.match(rendered, /Parallelism 2 lanes/);
  assert.match(rendered, /Migrations governed/);
  assert.match(rendered, /\/yoke blitz YOK-2001/);
  assert.doesNotMatch(rendered, /THIS PLAN BODY MUST NOT BE COPIED/);
  assert.equal(requests[0].function, "strategy.execution.get");
  assert.equal(requests[0].target.item_ref, "YOK-2001");
});
