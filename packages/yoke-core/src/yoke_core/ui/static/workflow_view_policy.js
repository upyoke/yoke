import { el } from "./universe_view_support.js";
import {
  readablePolicyValue,
  workflowPanel,
} from "./workflow_view_primitives.js";

/** What a workflow may never set, whatever its definition says. */
const UNIVERSAL_INVARIANTS = [
  ["Database changes", "governed migrations on every change"],
];

/**
 * Every setting this grid shows, in one list, whether or not the definition
 * declares it.
 *
 * A row that disappears when its value is uninteresting teaches the operator
 * that the setting does not exist, which is the opposite of what an absent
 * value means: absent means the engine's default applies. Each entry names
 * the fallback the engine itself uses, so an undeclared setting reports that
 * default and says it is one.
 *
 * Not showing a setting the definition's own schema version never had is a
 * different thing entirely, and stays: the grid describes the version being
 * viewed, so a row for a field that generation could not express would be
 * inventing one. ``sinceSchema`` draws that line; nothing here is hidden for
 * having an uninteresting value.
 */
export const POSTURE_POLICY_ROWS = [
  ["Ownership", "ownership", null, 1],
  ["Child items", "generated_children", null, 1],
  ["File Budget", "file_budget", "optional", 2],
  ["Path survey", "path_survey", "required", 1],
  ["Path claims", "path_claims", "optional", 1],
  ["Worktrees", "worktrees", null, 1],
];

export const COORDINATION_LEVELS = [
  { id: "none", label: "No prevention" },
  { id: "survey", label: "Path survey" },
  { id: "claims", label: "Path claims" },
];

/**
 * Which tier a row belongs to, and therefore where it sorts and what marks it.
 *
 * Locked-for-everyone and locked-by-this-workflow are different facts about a
 * setting, and one padlock for both says neither. Ordering the grid by how
 * changeable a row is puts the fixed ground first and everything an operator
 * can act on last.
 */
const TIER_INVARIANT = 0;
const TIER_WORKFLOW_FIXED = 1;
const TIER_PER_ITEM = 2;

function policyValue(policies, key, fallback) {
  const declared = policies[key];
  if (declared !== undefined && declared !== null) {
    return { value: declared, declared: true };
  }
  return { value: fallback, declared: false };
}

export function definitionPostureRows(definition = {}) {
  const policies = definition.policies || {};
  const schema = Number(definition.schema_version || 1);
  return POSTURE_POLICY_ROWS.map(([label, key, fallback, sinceSchema]) => {
    const { value, declared } = policyValue(policies, key, fallback);
    return {
      label,
      key,
      value,
      declared,
      expressible: declared || schema >= sinceSchema,
      tier: TIER_WORKFLOW_FIXED,
    };
  });
}

export function coordinationLevel(policies = {}) {
  if (["required", "required_per_task"].includes(policies.path_claims)) {
    return "claims";
  }
  return (policies.path_survey ?? "required") === "required"
    ? "survey"
    : "none";
}

function coordinationRow(workflow) {
  const policies = workflow.definition?.policies || {};
  const allowlist = new Set(policies.item_posture_allowlist || []);
  const tunable = allowlist.has("path_claims") &&
    allowlist.has("path_survey") &&
    ["optional", "required"].includes(policies.path_claims) &&
    ["optional", "required"].includes(policies.path_survey ?? "required");
  return {
    label: "Preventing overlapping work",
    key: "coordination",
    value: coordinationLevel(policies),
    declared: true,
    tunable,
    expressible: true,
    tier: tunable ? TIER_PER_ITEM : TIER_WORKFLOW_FIXED,
  };
}

export function postureRows(workflow) {
  const definition = workflow.definition || {};
  const rows = definitionPostureRows(definition)
    .filter((row) => !["path_claims", "path_survey"].includes(row.key))
    .filter((row) =>
      row.expressible && row.value !== undefined && row.value !== null);
  rows.push(coordinationRow(workflow));
  for (const [label, value] of UNIVERSAL_INVARIANTS) {
    rows.push({
      label,
      key: null,
      value,
      declared: true,
      tunable: false,
      tier: TIER_INVARIANT,
    });
  }
  // Stable within a tier: the declaration order above is deliberate, so only
  // the tier reorders anything.
  return rows
    .map((row, index) => ({ row, index }))
    .sort((left, right) =>
      left.row.tier - right.row.tier || left.index - right.index)
    .map((entry) => entry.row);
}

function lockPill(documentNode, row, workflowName) {
  const invariant = row.tier === TIER_INVARIANT;
  const pill = el(
    documentNode,
    "span",
    `workflow-lock-pill ${invariant ? "universal" : "workflow"}`,
    `🔒 ${invariant ? "Always" : workflowName}`,
  );
  pill.title = invariant
    ? "No workflow can change this"
    : `Fixed by every ${workflowName}`;
  return pill;
}

function postureCell(documentNode, row, workflowName, edit) {
  const cell = el(
    documentNode,
    "div",
    `workflow-posture-cell${edit ? " editable" : ""}`,
  );
  const copy = el(documentNode, "div", "workflow-posture-copy");
  const heading = el(documentNode, "div", "workflow-posture-label");
  heading.appendChild(el(
    documentNode, "span", "workflow-posture-name", row.label,
  ));
  if (!edit) heading.appendChild(lockPill(documentNode, row, workflowName));
  copy.appendChild(heading);
  copy.appendChild(el(
    documentNode, "div", "workflow-posture-value", postureValueText(row),
  ));
  cell.appendChild(copy);
  if (edit) {
    const control = el(
      documentNode, "button", "workflow-button compact", edit.label,
    );
    control.type = "button";
    control.addEventListener("click", edit.action);
    cell.appendChild(control);
  }
  return cell;
}

function postureValueText(row) {
  if (row.key === "coordination") {
    return COORDINATION_LEVELS.find(
      (level) => level.id === row.value,
    )?.label || row.value;
  }
  const readable = row.key
    ? readablePolicyValue(row.key, row.value)
    : row.value;
  if (row.tunable) {
    const on = row.value === "required";
    return `${on ? "on" : "off"} by default`;
  }
  // An undeclared setting says so rather than presenting the engine fallback
  // as this workflow's own choice.
  return row.declared ? readable : `${readable} (default)`;
}

export function renderPosture(documentNode, workflow, actions = {}) {
  const { panel, body } = workflowPanel(documentNode, "Execution posture");
  const grid = el(documentNode, "div", "workflow-posture-grid");
  const workflowName = workflow.name || workflow.id;
  for (const row of postureRows(workflow)) {
    const editAction = row.key === "coordination"
      ? actions.editCoordination
      : null;
    grid.appendChild(postureCell(
      documentNode,
      row,
      workflowName,
      row.tunable && editAction
        ? {
          label: "Change",
          action: editAction,
        }
        : null,
    ));
  }
  body.appendChild(grid);
  return panel;
}
