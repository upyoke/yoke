import assert from "node:assert/strict";

import {
  byClass,
  FakeDocument,
  FakeNode,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  workflowFixture,
} from "./universe_ui_workflows_test_support.mjs";

export const DESCRIPTIONS = {
  dash:
    "A short instruction you file in seconds — filing is the spec; " +
    "an agent executes it end-to-end.",
  blitz:
    "Execute a strategy document directly; the item is only its " +
    "coordination shell. Releases happen continuously inside implementing; " +
    "the close reconciles the document.",
  issue:
    "One scoped implementation lane with planning, review, QA and delivery.",
  epic:
    "Planned task decomposition with parallel worktree lanes and an " +
    "integration boundary.",
};

export const STAGES = {
  dash: [
    "idea",
    "implementing",
    "reviewing-implementation",
    "done",
  ],
  blitz: [
    "idea",
    "refining-idea",
    "refined-idea",
    "implementing",
    "reviewing-implementation",
    "done",
  ],
  issue: [
    "idea",
    "refining-idea",
    "refined-idea",
    "implementing",
    "reviewing-implementation",
    "reviewed-implementation",
    "polishing-implementation",
    "implemented",
    "release",
    "done",
  ],
  epic: [
    "idea",
    "refining-idea",
    "refined-idea",
    "planning",
    "plan-drafted",
    "refining-plan",
    "planned",
    "implementing",
    "reviewing-implementation",
    "reviewed-implementation",
    "polishing-implementation",
    "implemented",
    "release",
    "done",
  ],
};

const POLICY = {
  dash: {
    ownership: "exclusive_session_work_claim",
    path_claims: "optional",
    worktrees: "single_implementation_lane",
    parallelism: "none",
    generated_children: "none",
    qa: "optional_item_attachment",
    approvals: "none",
    delivery: "after_merge_action",
    item_posture_allowlist: [
      "verification", "path_claims", "approval_on_done", "deployment",
    ],
  },
  blitz: {
    ownership: "session_item_and_document_claim",
    path_claims: "optional",
    worktrees: "worker_lanes_optional_integration",
    parallelism: "maximum_safe_slices",
    generated_children: "none",
    qa: "item_attachments",
    approvals: "optional_named_gate",
    delivery: "continuous_slice_actions",
    item_posture_allowlist: ["verification"],
  },
  issue: {
    ownership: "single_item_claim",
    path_claims: "required",
    worktrees: "single_implementation_lane",
    parallelism: "inside_item",
    generated_children: "none",
    qa: "project_transition_defaults",
    approvals: "definition_transitions",
    delivery: "release_stage",
    item_posture_allowlist: ["verification"],
  },
  epic: {
    ownership: "item_claim_and_task_lanes",
    path_claims: "required_per_task",
    worktrees: "worker_and_integration_lanes",
    parallelism: "task_graph",
    generated_children: "epic_tasks",
    qa: "project_and_task_attachments",
    approvals: "definition_transitions",
    delivery: "release_stage",
    item_posture_allowlist: ["verification"],
  },
};

const EXECUTORS = {
  dash: ["dash"],
  blitz: ["refine", "blitz"],
  issue: ["refine", "advance", "polish", "usher"],
  epic: ["refine", "shepherd", "refine", "conduct", "polish", "usher"],
};

export function prototypeWorkflow(id) {
  const workflow = workflowFixture({
    id,
    name: `${id[0].toUpperCase()}${id.slice(1)}`,
    description: DESCRIPTIONS[id],
    currentVersion: 1,
    stages: STAGES[id].map((stageId, index) => ({
      id: stageId,
      label: stageId,
      gates: index
        ? [{ id: "evidence_check", mode: index === 1 ? "strict" : undefined }]
        : [],
    })),
    policies: POLICY[id],
    executorBindings: EXECUTORS[id].map((executorId) => ({
      executor_id: executorId,
      from_stage_id: STAGES[id][0],
      through_stage_id: STAGES[id].at(-1),
    })),
  });
  workflow.definition.entry_surfaces = id === "dash"
    ? ["web_form", "cli", "harness_skill", "promotion"]
    : id === "issue"
      ? ["harness_skill", "promotion"]
      : ["harness_skill"];
  return workflow;
}

export async function selectWorkflow(documentNode, root, name) {
  const tab = byClass(root, "workflow-tab").find(
    (node) => node.textContent === name,
  );
  assert.ok(tab, `${name} tab exists`);
  tab.dispatchEvent(new Event("click"));
  documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  await settle();
}

export function cssRule(source, selector) {
  const start = source.indexOf(selector);
  assert.notEqual(start, -1, `${selector} exists`);
  return source.slice(start, source.indexOf("}", start) + 1);
}

export function enableTextNodes(t) {
  const original = FakeDocument.prototype.createTextNode;
  FakeDocument.prototype.createTextNode = function createTextNode(value) {
    const node = new FakeNode(this, "#text", 3);
    node.textContent = String(value);
    return node;
  };
  t.after(() => {
    if (original) FakeDocument.prototype.createTextNode = original;
    else delete FakeDocument.prototype.createTextNode;
  });
}
