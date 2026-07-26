import assert from "node:assert/strict";
import test from "node:test";

import {
  renderItemDetailView,
  renderItemsView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_items.js";
import { renderNewItemView } from "../../packages/yoke-core/src/yoke_core/ui/static/item_view_new.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function context(documentNode, call) {
  return {
    client: { call },
    document: documentNode,
    isMounted: () => true,
    projects: () => [{ id: 7, slug: "acme", name: "Acme" }],
    capabilities: {},
  };
}

function text(root) {
  return allNodes(root).map((node) => node.textContent || "").join(" ");
}

test("Items is one workflow roster with distinct owner and claim facts", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const requests = [];
  renderItemsView(context(documentNode, async (request) => {
    requests.push(request);
    return {
      status: 200,
      envelope: {
        success: true,
        result: {
          count: 2,
          rows: [
            {
              id: 41,
              public_ref: "ACM-12",
              project_id: 7,
              title: "Ship the direct fix",
              workflow_id: "dash",
              workflow_version_id: 3,
              status: "reviewing-implementation",
              owner: "Rae",
              claimed_by: {
                actor_label: "build-system",
                session_id: "session-a",
              },
            },
            {
              id: 42,
              public_ref: "ACM-13",
              project_id: 7,
              title: "Plan the boundary",
              workflow_id: "epic",
              workflow_version_id: 2,
              status: "planned",
              owner: "",
              claimed_by: null,
            },
          ],
        },
      },
    };
  }), root, "all");
  await settle();

  assert.deepEqual(requests, [{
    function: "items.overview.list",
    payload: {},
  }]);
  assert.equal(byClass(root, "item-workflow").length, 2);
  assert.match(text(root), /ACM-12/);
  assert.match(text(root), /Ship the direct fix/);
  assert.match(text(root), /Rae/);
  assert.match(text(root), /build-system/);
  assert.match(text(root), /unassigned/);
  assert.ok(!text(root).includes("priority"));
  const hrefs = byClass(root, "row-link").map((node) => node.href);
  assert.deepEqual(hrefs, [
    "#/items/ACM-12?project=7",
    "#/items/ACM-13?project=7",
  ]);
  assert.equal(byClass(root, "panel-count")[0].textContent, "· 2");
  assert.equal(byClass(root, "item-action")[0].href, "#/items/new?project=7");
});

function detailItem(workflowId) {
  return {
    id: 51,
    public_ref: "ACM-22",
    title: workflowId === "dash" ? "Fix the footer" : "Build the shell",
    status: "reviewing-implementation",
    priority: "medium",
    owner: "Rae",
    blocked: false,
    blocked_reason: "",
    created_at: "2026-07-25T12:00:00Z",
    updated_at: "2026-07-26T12:00:00Z",
    project: { id: 7, slug: "acme", name: "Acme" },
    workflow: {
      id: workflowId,
      name: workflowId === "dash" ? "Dash" : "Issue",
      version: 4,
      stage_label: "Reviewing implementation",
      executor_id: workflowId,
      next_executor_id: workflowId === "issue" ? "polish" : workflowId,
      policies: {
        path_claims: workflowId === "dash" ? "optional" : "required",
        worktrees: "single_implementation_lane",
        parallelism: "none",
        generated_children: "none",
        delivery: "after_merge_action",
      },
    },
    claim: {
      actor_label: "Codex",
      session_id: "session-z",
    },
    worktrees: [{
      branch: "codex/footer",
      lane_role: "implementation",
      state: "active",
    }],
    path_claims: { total: 0, states: {} },
    narrative: {
      spec: workflowId === "dash"
        ? "Correct the footer typo and verify every link."
        : "Build one shell.\n\n## Acceptance Criteria\n- [ ] Focus stays put.",
      body: "",
      shepherd_log: "",
      worktree_plan: "",
    },
    progress_log: {
      content: "## 2026-07-26 entry — renderer built\nReal values landed.",
    },
    qa_requirements: [{
      id: 5,
      qa_kind: "browser-inspection",
      qa_phase: "reviewing-implementation",
      blocking_mode: "blocking",
      requirement_source: "footer-renders",
      verdict: "needs review",
      execution_status: "completed",
    }],
  };
}

for (const workflowId of ["issue", "dash"]) {
  test(`${workflowId} detail renders its prototype-specific spine from the read model`, async () => {
    const documentNode = new FakeDocument();
    const root = documentNode.createElement("div");
    const requests = [];
    renderItemDetailView(context(documentNode, async (request) => {
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
    const rendered = text(root);
    assert.match(rendered, workflowId === "dash" ? /Instruction/ : /Spec/);
    assert.match(rendered, /Item details/);
    assert.match(rendered, /Verification/);
    assert.match(rendered, /Execution posture/);
    assert.match(rendered, /Run in a harness/);
    assert.match(rendered, /footer-renders/);
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
      assert.match(rendered, /Progress Log/);
    }
  });
}

test("New item derives web-fileability and settings from the definition", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const workflows = [
    {
      id: "issue",
      name: "Issue",
      definition: { entry_surfaces: ["harness_skill"], policies: {} },
    },
    {
      id: "dash",
      name: "Dash",
      definition: {
        entry_surfaces: ["web_form", "cli", "harness_skill", "promotion"],
        policies: {
          item_posture_allowlist: [
            "verification", "path_claims", "approval_on_done", "deployment",
          ],
        },
      },
    },
  ];
  const requests = [];
  renderNewItemView(context(documentNode, async (request) => {
    requests.push(request);
    const result = request.function === "workflows.definition.get"
      ? { workflows }
      : request.function === "qa.plan.list"
        ? { rows: [{ id: 3, slug: "browser-close" }] }
        : { rows: [{ id: "browser-inspection", name: "Browser inspection" }] };
    return { status: 200, envelope: { success: true, result } };
  }), root, "7");
  await settle();

  const rendered = text(root);
  assert.match(rendered, /New Dash/);
  assert.match(rendered, /Only Dash can currently be filed from the web/);
  assert.match(rendered, /Issue is filed in a harness \(\/yoke idea\)/);
  assert.match(rendered, /Title/);
  assert.match(rendered, /Instruction/);
  assert.match(rendered, /Verification/);
  assert.match(rendered, /Path claims/);
  assert.match(rendered, /Approval on done/);
  assert.match(rendered, /Deploy after merge/);
  assert.equal(byClass(root, "item-setting-row").length, 4);
  assert.deepEqual(requests.map((request) => request.function), [
    "workflows.definition.get",
    "qa.plan.list",
    "qa.method.list",
  ]);

  const verification = byClass(root, "item-setting-row")[0];
  byClass(verification, "item-button")[0].dispatchEvent(new Event("click"));
  const enabled = text(root);
  assert.match(enabled, /plan · browser-close/);
  assert.match(enabled, /ad hoc · Browser inspection/);
  assert.match(enabled, /runs at reviewing-implementation/);
});

test("New item submits one atomic create and routes to the public ref", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const requests = [];
  let destination = null;
  const viewContext = context(documentNode, async (request) => {
    requests.push(request);
    if (request.function === "workflows.definition.get") {
      return {
        status: 200,
        envelope: {
          success: true,
          result: {
            workflows: [{
              id: "dash",
              name: "Dash",
              definition: {
                entry_surfaces: ["web_form"],
                policies: {
                  item_posture_allowlist: [
                    "verification", "path_claims", "approval_on_done",
                  ],
                },
              },
            }],
          },
        },
      };
    }
    if (request.function === "qa.plan.list") {
      return {
        status: 200,
        envelope: { success: true, result: { rows: [{ id: 3, slug: "smoke" }] } },
      };
    }
    if (request.function === "qa.method.list") {
      return {
        status: 200,
        envelope: { success: true, result: { rows: [] } },
      };
    }
    return {
      status: 200,
      envelope: { success: true, result: { item_ref: "ACM-23" } },
    };
  });
  viewContext.navigate = (route) => { destination = route; };
  renderNewItemView(viewContext, root, "7");
  await settle();

  byClass(byClass(root, "item-setting-row")[0], "item-button")[0]
    .dispatchEvent(new Event("click"));
  byClass(byClass(root, "item-setting-row")[1], "item-button")[0]
    .dispatchEvent(new Event("click"));
  const input = allNodes(root).find((node) => node.tagName === "INPUT");
  const textarea = allNodes(root).find((node) => node.tagName === "TEXTAREA");
  input.value = "Fix the footer";
  textarea.value = "Correct it and verify every link.";
  allNodes(root).find((node) => node.tagName === "FORM")
    .dispatchEvent(new Event("submit"));
  await settle();

  const create = requests.find((request) => request.function === "items.create");
  assert.deepEqual(create.payload, {
    title: "Fix the footer",
    instruction: "Correct it and verify every link.",
    project: "acme",
    workflow: "dash",
    entry_surface: "web_form",
    workflow_posture: {
      verification: { kind: "plan", plan_id: 3 },
      path_claims: true,
    },
  });
  assert.equal(destination, "#/items/ACM-23?project=7");
});
