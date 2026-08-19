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
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";

const BLITZ_POLICIES = {
  file_budget: "optional",
  path_claims: "optional",
  worktrees: "worker_lanes_optional_integration",
  generated_children: "none",
  delivery: "continuous",
};

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
  const now = Date.now();
  return {
    slug: "WORKFLOW-TYPES",
    content: [
      "# WORKFLOW-TYPES",
      "",
      "## Purpose",
      "",
      "Execute **the plan** with `yoke`.",
      "",
      "1. Render",
      "2. Review",
      "",
      "## Decisions",
      "",
      "- Keep one authority.",
    ].join("\n"),
    updated_at: "2026-07-26T12:00:00Z",
    updated_by: "ben",
    bytes: 31 * 1024,
    parent_slug: "MASTER-PLAN",
    references: ["MASTER-PLAN"],
    current_revision: 2,
    pending_review_count: 1,
    review_requests: [{ id: 7, status: "pending" }],
    execution_claim: {
      owning_item_id: 2262, project_id: 1,
      item_ref: "YOK-2001",
      workflow_id: "blitz",
      workflow_version_id: 17,
      workflow_version: 2,
    },
    revisions: [
      {
        revision: 2,
        source_operation: "ingest",
        operation_label: "ingested",
        change_summary: "Full implementation plan ingested",
        byte_length: 31 * 1024,
        line_count: 398,
        content_sha256: "d0fdad55aa",
        created_at: new Date(now - 12 * 60 * 1000).toISOString(),
      },
      {
        revision: 1,
        source_operation: "create",
        operation_label: "created",
        change_summary: "Initial title only",
        byte_length: 16,
        line_count: 1,
        content_sha256: "4dece4a3bb",
        created_at: new Date(now - 23 * 60 * 1000).toISOString(),
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
  assert.deepEqual(
    allNodes(byClass(main, "strategy-corpus-table")[0])
      .filter((node) => node.tagName === "TH")
      .map((node) => node.textContent),
    [
      "Doc", "Purpose / ancestry", "Last editor", "Last write",
      "Revisions", "Execution",
    ],
  );
  const spark = byClass(main, "strategy-spark")[0];
  assert.equal(spark.tagName, "SVG");
  assert.equal(spark.attributes.get("viewBox"), "0 0 240 34");
  assert.ok(allNodes(spark).some((node) => node.tagName === "POLYGON"));
  assert.ok(allNodes(spark).some((node) => node.tagName === "POLYLINE"));
  assert.equal(requests[0].function, "strategy.surface.list");
  assert.deepEqual(requests[0].target, {
    kind: "global", project_id: "1",
  });
  const row = byClass(main, "strategy-corpus-row")[0];
  assert.equal(row.attributes.get("role"), "link");
  row.dispatchEvent(new Event("click"));
  assert.equal(
    documentNode.defaultView.location.hash,
    "#/strategy/WORKFLOW-TYPES?project=1",
  );
  assert.ok(allNodes(main).some((node) => node.tagName === "TIME"));
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
  assert.equal(byClass(main, "page-head").length, 1);
  assert.match(rendered, /State & actions/);
  assert.match(rendered, /Approve revision 2/);
  assert.match(rendered, /Author through a harness/);
  assert.match(rendered, /Inspect documents, compare revisions/);
  assert.doesNotMatch(rendered, /\bcomments?\b/i);
  assert.match(rendered, /item-owned\s+·\s+YOK-2001/);
  assert.equal(allNodes(main).find((node) => node.textContent === "YOK-2001 →").href, "#/items/2001?project=1");
  assert.match(rendered, /Blitz v2/);
  assert.match(rendered, /Purpose/);
  assert.doesNotMatch(rendered, /<h1>/);
  const documentBody = byClass(main, "strategy-document")[0];
  assert.equal(
    allNodes(documentBody).some(
      (node) => ["H2", "H3"].includes(node.tagName)
        && node.children.some((child) => child.textContent === "WORKFLOW-TYPES"),
    ),
    false,
  );
  assert.ok(allNodes(documentBody).some((node) => node.tagName === "STRONG"));
  assert.ok(allNodes(documentBody).some((node) => node.tagName === "CODE"));
  assert.ok(allNodes(documentBody).some((node) => node.tagName === "OL"));
  assert.match(rendered, /revision 2/);
  assert.ok(allNodes(main).some(
    (node) => node.attributes.get("data-state") === "pending",
  ));
  assert.ok(allNodes(main).some(
    (node) => node.attributes.get("data-state") === "item-owned",
  ));

  const history = allNodes(main).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "History",
  );
  history.dispatchEvent(new Event("click"));
  rendered = text(main);
  assert.match(rendered, /Revision history/);
  assert.match(rendered, /Revision 2 · current/);
  assert.match(
    rendered,
    /Full implementation plan ingested · 31 KB\s+·\s+d0fdad55…/,
  );
  assert.match(rendered, /Revision 1 · created/);
  assert.match(rendered, /Initial title only · 16 B\s+·\s+4dece4a3…/);
  assert.match(rendered, /12m/);
  assert.match(rendered, /23m/);
  assert.match(rendered, /Restore creates revision 3/);
  assert.match(rendered, /\+397 lines/);
  assert.ok(allNodes(main).some((node) => node.tagName === "TIME"));

  const viewDiff = allNodes(main).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "View diff",
  );
  viewDiff.dispatchEvent(new Event("click"));
  await settle();
  assert.match(text(main), /\+Keep one authority/);
  assert.match(text(main), /\+1 \/ −0 lines/);
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
      skill_id: "blitz",
      policies: { ...BLITZ_POLICIES },
      effective_policies: { ...BLITZ_POLICIES },
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
      {
        lane_role: "worker",
        branch: "codex/qa-types",
        state: "committed",
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
  assert.match(rendered, /codex\/qa-types\s+slice committed/);
  assert.match(rendered, /Parallelism 3 lanes/);
  assert.match(rendered, /Migrations governed/);
  assert.match(rendered, /\/yoke blitz YOK-2001/);
  assert.doesNotMatch(rendered, /THIS PLAN BODY MUST NOT BE COPIED/);
  assert.equal(requests[0].function, "strategy.execution.get");
  assert.equal(requests[0].target.item_ref, "YOK-2001");
});
