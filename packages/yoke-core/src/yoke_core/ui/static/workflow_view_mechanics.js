import { el } from "./universe_view_support.js";
import {
  approvalSummary,
  deliverySummary,
  testingSummary,
} from "./workflow_mechanics_data.js";
import {
  setWorkflowInlineContent,
  stageDisplayLabel,
  workflowPanel,
} from "./workflow_view_primitives.js";

const MECHANIC_DESTINATION_LABELS = {
  "qa-plans": "QA plans",
  inbox: "Inbox",
  deployments: "Deployments",
  strategy: "Strategy",
};

function testingMechanicSummary(mechanics, workflow) {
  return testingSummary(mechanics, workflow);
}

function deliveryMechanicSummary(mechanics, workflow) {
  return deliverySummary(mechanics, workflow);
}

const SKILL_SUMMARIES_BY_BINDING = {
  "dash:dash": [
    "Run ",
    { kind: "code", text: "/yoke dash" },
    " in a supported harness like Claude Code or Codex — it runs the whole " +
      "item: survey, worktree, execute, verify, merge, evidence.",
  ],
  "blitz:refine>blitz": [
    "Run ",
    { kind: "code", text: "/yoke refine" },
    " then ",
    { kind: "code", text: "/yoke blitz" },
    " in a supported harness like Claude Code or Codex — blitz executes the " +
      "linked document directly, in continuous slices; nothing is copied.",
  ],
  "issue:refine>advance>polish>usher": [
    "Run ",
    { kind: "code", text: "/yoke refine" },
    ", ",
    { kind: "code", text: "advance" },
    ", ",
    { kind: "code", text: "polish" },
    ", ",
    { kind: "code", text: "usher" },
    " in a supported harness like Claude Code or Codex.",
  ],
  "epic:refine>shepherd>refine>conduct>polish>usher": [
    "Run ",
    { kind: "code", text: "/yoke refine" },
    ", ",
    { kind: "code", text: "shepherd" },
    ", ",
    { kind: "code", text: "conduct" },
    ", ",
    { kind: "code", text: "polish" },
    ", ",
    { kind: "code", text: "usher" },
    " in a supported harness like Claude Code or Codex.",
  ],
};

function skillSummary(workflow) {
  const definition = workflow.definition || {};
  const skills = (definition.skill_bindings || [])
    .map((binding) => binding.skill_id);
  if (!skills.length) return "No registered skill.";
  const servedBindingKey = `${workflow.id}:${skills.join(">")}`;
  if (SKILL_SUMMARIES_BY_BINDING[servedBindingKey]) {
    return SKILL_SUMMARIES_BY_BINDING[servedBindingKey];
  }
  return [
    "Run ",
    ...skills.flatMap((value, index) => [
      ...(index ? [" → "] : []),
      { kind: "code", text: `/yoke ${value}` },
    ]),
    " in a supported harness.",
  ];
}

function mechanicRow(
  documentNode, title, description, route, action = null,
) {
  const row = el(documentNode, "div", "workflow-detail-row");
  const content = el(documentNode, "div", "workflow-detail-content");
  content.appendChild(el(
    documentNode, "div", "workflow-detail-row-title", title,
  ));
  const descriptionNode = el(
    documentNode, "div", "workflow-detail-row-description",
  );
  setWorkflowInlineContent(documentNode, descriptionNode, description);
  content.appendChild(descriptionNode);
  row.appendChild(content);
  if (route) {
    const destination = MECHANIC_DESTINATION_LABELS[route] || title;
    const link = el(
      documentNode, "a", "workflow-home-link", `${destination} →`,
    );
    link.href = `#/${route}`;
    row.appendChild(link);
  }
  if (action) {
    const control = el(
      documentNode, "button", "workflow-button compact",
      action.label,
    );
    control.type = "button";
    control.addEventListener("click", action.run);
    row.appendChild(control);
  }
  return row;
}

function approvalSummaryWithStageLabels(mechanics, workflow) {
  let summary = approvalSummary(mechanics, workflow);
  for (const stage of workflow.definition?.stages || []) {
    summary = summary.replaceAll(
      `${stage.id} →`,
      `${stageDisplayLabel(stage)} →`,
    );
  }
  return summary;
}

export function renderMechanics(documentNode, workflow, actions = {}) {
  const definition = workflow.definition || {};
  const policies = definition.policies || {};
  const mechanics = actions.mechanics || {
    testingDefaults: [],
    deliveryDefaults: [],
    approvers: [],
  };
  const workflowName = workflow.name || workflow.id;
  const { panel, body } = workflowPanel(documentNode, "Mechanics");
  const rows = el(documentNode, "div", "workflow-detail-stack");
  rows.appendChild(mechanicRow(
    documentNode,
    "Skill",
    skillSummary(workflow),
    workflow.id === "blitz" ? "strategy" : null,
  ));
  rows.appendChild(mechanicRow(
    documentNode,
    "Testing",
    testingMechanicSummary(mechanics, workflow),
    "qa-plans",
    actions.editTesting
      ? {
        label: `Edit ${workflowName} defaults for each project`,
        run: actions.editTesting,
      }
      : null,
  ));
  rows.appendChild(mechanicRow(
    documentNode,
    "Approvals",
    approvalSummaryWithStageLabels(mechanics, workflow),
    "inbox",
    actions.editApprovals
      ? {
        label:
          `${Object.keys(policies.approval_defaults || {}).length
            ? "Edit" : "Set"} universe defaults for ${workflowName}`,
        run: actions.editApprovals,
      }
      : null,
  ));
  rows.appendChild(mechanicRow(
    documentNode,
    "Delivery",
    deliveryMechanicSummary(mechanics, workflow),
    "deployments",
    actions.editDelivery
      ? {
        label: `Edit ${workflowName} defaults for each project`,
        run: actions.editDelivery,
      }
      : null,
  ));
  body.appendChild(rows);
  return panel;
}
