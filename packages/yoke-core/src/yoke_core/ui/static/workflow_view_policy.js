import { el } from "./universe_view_support.js";
import {
  readablePolicyValue,
  workflowPanel,
} from "./workflow_view_primitives.js";

const MECHANIC_COPY = {
  qa: {
    project_transition_defaults: "the project defaults, per transition",
    project_and_task_attachments:
      "the project defaults plus per-task attachments",
    item_attachments: "attached to the item",
    optional_item_attachment: "none required by default",
  },
  approvals: {
    definition_transitions: "per the definition transitions",
    optional_named_gate: "an optional named gate",
    none: "none by default",
  },
  delivery: {
    release_stage:
      "at the release stage; the flow is selected from the project's flows",
    continuous_slice_actions:
      "continuously as slices merge; the flow is selected per item",
    after_merge_action:
      "as an after-merge action; the flow is selected per item",
  },
};

function postureRows(workflow) {
  const policies = workflow.definition?.policies || {};
  const rows = [
    ["Ownership", "ownership", policies.ownership],
    ["Path claims", "path_claims", policies.path_claims],
    ["Worktrees", "worktrees", policies.worktrees],
  ];
  if (policies.parallelism !== "none") {
    rows.push(["Parallelism", "parallelism", policies.parallelism]);
  }
  if (
    policies.generated_children === "none" &&
    ["optional_item_attachment", "item_attachments"].includes(policies.qa)
  ) {
    rows.push([
      "Child items", "generated_children", policies.generated_children,
    ]);
  }
  return rows;
}

function postureCell(documentNode, label, value, edit = null) {
  const cell = el(
    documentNode,
    "div",
    `workflow-posture-cell${edit ? " editable" : ""}`,
  );
  const heading = el(documentNode, "div", "workflow-posture-label");
  if (!edit) {
    heading.appendChild(el(documentNode, "span", "workflow-lock", "🔒"));
  }
  heading.appendChild(el(documentNode, "span", null, label));
  cell.appendChild(heading);
  const valueRow = el(documentNode, "div", "workflow-posture-value-row");
  valueRow.appendChild(el(
    documentNode, "div", "workflow-posture-value", value,
  ));
  if (edit) {
    const control = el(
      documentNode, "button", "workflow-button compact",
      edit.label,
    );
    control.type = "button";
    control.addEventListener("click", edit.action);
    valueRow.appendChild(control);
  }
  cell.appendChild(valueRow);
  return cell;
}

export function renderPosture(documentNode, workflow, actions = {}) {
  const { panel, body } = workflowPanel(documentNode, "Execution posture");
  const grid = el(documentNode, "div", "workflow-posture-grid");
  for (const [label, policy, value] of postureRows(workflow)) {
    const pathClaimsEditable = policy === "path_claims" &&
      (workflow.definition?.policies?.item_posture_allowlist || [])
        .includes("path_claims") &&
      ["optional", "required"].includes(value);
    const pathClaimsOn = value === "required";
    grid.appendChild(postureCell(
      documentNode,
      label,
      pathClaimsEditable
        ? `${pathClaimsOn ? "on" : "off"} by default`
        : readablePolicyValue(policy, value),
      pathClaimsEditable && actions.editPathClaims
        ? {
          label: pathClaimsOn ? "Turn off" : "Turn on",
          action: () => actions.editPathClaims(!pathClaimsOn),
        }
        : null,
    ));
  }
  grid.appendChild(postureCell(
    documentNode,
    "Database changes",
    "governed migrations on every change",
  ));
  body.appendChild(grid);
  return panel;
}

function executorSummary(definition) {
  const executors = (definition.executor_bindings || [])
    .map((binding) => binding.executor_id);
  if (!executors.length) return "No registered executor.";
  return `Run ${executors.map((value) => `/yoke ${value}`).join(" → ")} ` +
    "in a supported harness.";
}

function mechanicRow(documentNode, title, description, route) {
  const row = el(documentNode, "div", "workflow-detail-row");
  const content = el(documentNode, "div", "workflow-detail-content");
  content.appendChild(el(
    documentNode, "div", "workflow-detail-row-title", title,
  ));
  content.appendChild(el(
    documentNode,
    "div",
    "workflow-detail-row-description",
    description,
  ));
  row.appendChild(content);
  if (route) {
    const link = el(documentNode, "a", "workflow-home-link", `${title} →`);
    link.href = `#/${route}`;
    row.appendChild(link);
  }
  return row;
}

export function renderMechanics(documentNode, workflow) {
  const definition = workflow.definition || {};
  const policies = definition.policies || {};
  const { panel, body } = workflowPanel(documentNode, "Mechanics");
  const rows = el(documentNode, "div", "workflow-detail-stack");
  rows.appendChild(mechanicRow(
    documentNode, "Executor", executorSummary(definition),
  ));
  rows.appendChild(mechanicRow(
    documentNode,
    "Testing",
    `Test plans — ${MECHANIC_COPY.qa[policies.qa] ||
      readablePolicyValue("qa", policies.qa)}.`,
    "qa",
  ));
  rows.appendChild(mechanicRow(
    documentNode,
    "Approvals",
    `Approval policy — ${MECHANIC_COPY.approvals[policies.approvals] ||
      readablePolicyValue("approvals", policies.approvals)}.`,
    "inbox",
  ));
  rows.appendChild(mechanicRow(
    documentNode,
    "Delivery",
    `Deploys ${MECHANIC_COPY.delivery[policies.delivery] ||
      readablePolicyValue("delivery", policies.delivery)}.`,
    "delivery",
  ));
  body.appendChild(rows);
  return panel;
}
