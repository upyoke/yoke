import {
  allNodes,
} from "./universe_ui_dom_test_support.mjs";

export function itemContext(documentNode, call) {
  return {
    client: { call },
    document: documentNode,
    isMounted: () => true,
    projects: () => [{
      id: 7, slug: "acme", name: "Acme", emoji: "🐜",
    }],
    capabilities: {},
  };
}

export function itemText(root) {
  return allNodes(root).map(
    (node) => node.textContent || "",
  ).join(" ");
}

export function detailItem(workflowId) {
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
      name: {
        blitz: "Blitz",
        dash: "Dash",
        epic: "Epic",
        issue: "Issue",
      }[workflowId] || workflowId,
      version: 4,
      stage_label: "Reviewing implementation",
      executor_id: workflowId,
      next_executor_id: workflowId === "issue"
        ? "polish" : workflowId === "epic" ? "conduct" : workflowId,
      item_posture: {
        verification: true,
        file_budget: false,
        path_claims: false,
      },
      policies: {
        file_budget: ["dash", "blitz"].includes(workflowId)
          ? "optional"
          : workflowId === "epic" ? "required_per_task" : "required",
        path_claims: ["dash", "blitz"].includes(workflowId)
          ? "optional"
          : workflowId === "epic" ? "required_per_task" : "required",
        worktrees: workflowId === "epic"
          ? "worker_and_integration_lanes"
          : workflowId === "blitz"
            ? "worker_lanes_optional_integration"
            : "single_implementation_lane",
        parallelism: workflowId === "epic"
          ? "task_graph"
          : workflowId === "blitz" ? "maximum_safe_slices"
            : workflowId === "issue" ? "inside_item" : "none",
        generated_children: workflowId === "epic" ? "epic_tasks" : "none",
        delivery: "after_merge_action",
      },
    },
    claim: {
      actor_label: "Codex",
      session_id: "session-z",
      claimed_at: "2026-07-26T10:00:00Z",
    },
    worktrees: [{
      branch: "codex/footer",
      lane_role: "implementation",
      state: "active",
    }],
    path_claims: { total: 0, states: {} },
    file_budget: workflowId === "issue"
      ? { total: 1, paths: ["packages/web/footer.js"] }
      : { total: 0, paths: [] },
    narrative: {
      spec: workflowId === "dash"
        ? "Correct the footer typo and verify every link."
        : "Build one shell.\n\n## Acceptance Criteria\n- [ ] Focus stays put.",
      body: "",
      shepherd_log: workflowId === "epic"
        ? "## Verdict\n\nReady to execute." : "",
      worktree_plan: workflowId === "epic"
        ? "- Task lanes activate independently." : "",
    },
    progress_log: {
      content: "## 2026-07-26 entry — renderer built\nReal values landed.",
    },
    qa_requirements: [{
      id: 5,
      run_id: 8,
      qa_kind: "browser-inspection",
      qa_phase: "reviewing-implementation",
      blocking_mode: "blocking",
      requirement_source: "footer-renders",
      plan_id: 3,
      plan_slug: "browser-close",
      plan_name: "Browser closeout",
      plan_case_key: "responsive-footer",
      method_id: "browser-inspection",
      method_name: "Browser inspection",
      expected_outcome: "The footer stays visible at both breakpoints.",
      outcome: "needs_review",
      proof_summary: workflowId === "dash"
        ? "screenshot the footer; the agent confirms the typo is gone and " +
          "the links still render"
        : "1 screenshot",
      evidence_count: 1,
      latest_evidence_type: "screenshot",
      verdict: "needs review",
      execution_status: "completed",
      workflow_transition_id: "reviewing-implementation",
      created_at: "2026-07-26T10:30:00Z",
    }],
    qa_plan_attachments: [
      {
        plan_id: 3,
        plan_slug: "browser-close",
        plan_name: "Browser closeout",
        transition_id: "reviewing-implementation",
        source: "project default",
        materialized_count: 1,
        materialized_at: "2026-07-26T10:30:00Z",
      },
      {
        plan_id: 4,
        plan_slug: "e2e-suite",
        plan_name: "End-to-end suite",
        transition_id: "release",
        source: "project default",
        materialized_count: 0,
      },
    ],
  };
}
