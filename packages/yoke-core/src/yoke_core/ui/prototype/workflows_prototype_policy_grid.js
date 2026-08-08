// The uniform policy grid: every key, every workflow, same order, no
// value-conditional hiding. A policy that is off says it is off; a key the
// pinned version predates says exactly that; a description that is not a knob
// is labelled as one and carries no lock.

import { el } from "./workflows_prototype_dom.js";

const ABSENT = Symbol("absent");

const MEANING = {
  ownership: {
    single_item_claim: "one active item claim",
    item_claim_and_task_lanes: "one epic claim, plus a claim per task lane",
    session_item_and_document_claim:
      "the session claims the item; the item claims its document",
    exclusive_session_work_claim:
      "one harness session holds the item exclusively",
  },
  file_budget: {
    optional: "off by default — items may opt in",
    required: "required on every item",
    required_per_task: "required on every generated task",
  },
  worktrees: {
    single_implementation_lane: "one implementation lane",
    worker_and_integration_lanes: "worker lanes plus an integration lane",
    worker_lanes_optional_integration:
      "worker lanes; integration lane only when needed",
  },
  generated_children: {
    none: "none — this workflow never generates child items",
    epic_tasks: "epic tasks, decomposed by the planning skill",
  },
  qa: {
    optional_item_attachment: "optional — cases attach to the item",
    item_attachments: "cases attach to the item",
    project_transition_defaults: "the project's defaults for each transition",
    project_and_task_attachments: "project defaults plus per-task cases",
  },
  approvals: {
    none: "none required",
    optional_named_gate: "one named gate, when the item asks for it",
    definition_transitions: "on the transitions this definition names",
  },
  delivery: {
    after_merge_action: "an action taken after merge",
    continuous_slice_actions: "continuously, per shipped slice",
    release_stage: "a release stage in the lifecycle",
  },
};

// Where the lever lives, and what happens when you pull it. A read-only grid
// names the lever without the edit clause: a published version is immutable,
// so "editing here" would describe something this view cannot do.
function lever(kind, workflow, editable) {
  if (kind === "derived") {
    return "Described, not configured — follows worktrees and child items.";
  }
  if (kind === "invariant") {
    return "Core invariant — never a workflow policy, on any workflow.";
  }
  const publishes = editable
    ? ` Changing the default here publishes ${workflow.name} v${
      workflow.current_version + 1}.`
    : "";
  if (kind === "posture") {
    return `Lever: per-item posture — an item opts in.${publishes}`;
  }
  return `Lever: publish a new version.${publishes}`;
}

// Every chip names the surface that consumes it. A chip whose enforcement
// nobody can name does not belong on this page.
const ENFORCED_BY = {
  ownership: "work-claim acquisition, and the work_claim_activation gate.",
  coordination:
    "the conflict_survey gate on entry, and the path-claim boundary gate " +
    "at done.",
  file_budget:
    "the 350-line authored-file limit (always on), and the File Budget " +
    "section when the axis is on.",
  worktrees: "worktree preparation, which creates exactly these lanes.",
  generated_children:
    "definition validation, which refuses epic tasks without a planning " +
    "skill that produces them.",
  lane_topology: "nothing directly — it reads worktrees and child items.",
  qa: "the QA case run at reviewing-implementation.",
  approvals: "the approval decision request raised on the gated transition.",
  delivery: "the item-bound deployment run started after merge.",
  database_changes:
    "the governed migration runner, its rehearsal receipt, and the boot " +
    "converge that applies the ordered history.",
};

function read(policies, key) {
  return Object.hasOwn(policies, key) ? policies[key] : ABSENT;
}

function meaning(key, value) {
  if (value === ABSENT) return null;
  return (MEANING[key] || {})[value] || String(value).replaceAll("_", " ");
}

// One rung, derived from the two stored axes. The ladder is how an operator
// thinks about coordination; the two axes are how it is stored, and both are
// shown rather than one standing in for the other.
function coordination(policies) {
  const claims = read(policies, "path_claims");
  const survey = read(policies, "path_survey");
  const claimsOn = claims === "required" || claims === "required_per_task";
  const rung = claimsOn
    ? "coordinated — survey the touch set, then register claims on it"
    : survey === "required"
      ? "aware — survey the touch set; claims stay optional"
      : "off — neither surveyed nor claimed";
  const axis = (label, value) => `${label}: ${
    value === ABSENT ? "not declared in this version" : value
  }`;
  return {
    value: rung,
    detail: "Stored as two axes — " +
      `${axis("path survey", survey)} · ${axis("path claims", claims)}`,
  };
}

// Lane topology replaces the parallelism policy, which nothing ever read. It
// describes the lanes the definition already produces, so it is a sentence
// about enforced behavior rather than a knob with its own value.
function laneTopology(policies) {
  const worktrees = read(policies, "worktrees");
  const children = read(policies, "generated_children");
  if (worktrees === ABSENT) return { value: ABSENT, detail: null };
  const parallel = worktrees !== "single_implementation_lane";
  return {
    value: children === "epic_tasks"
      ? "many lanes — one per generated task, joined at integration"
      : parallel
        ? "many lanes — opened as the work needs them"
        : "one lane — everything lands on a single branch",
    detail: null,
  };
}

function rows(workflow, policies) {
  const ladder = coordination(policies);
  const topology = laneTopology(policies);
  // Whether an axis is a per-item lever is the definition's own allowlist, not
  // an assumption about the axis: Issue and Epic enforce coordination at the
  // definition level, where an item cannot opt out of it.
  const posture = (...keys) => keys.some(
    (key) => (policies.item_posture_allowlist || []).includes(key),
  ) ? "posture" : "definition";
  return [
    { key: "ownership", label: "Ownership", kind: "definition",
      value: meaning("ownership", read(policies, "ownership")) },
    { key: "coordination", label: "Coordination",
      kind: posture("path_claims", "path_survey"),
      value: ladder.value, detail: ladder.detail },
    { key: "file_budget", label: "File Budget",
      kind: posture("file_budget"),
      value: meaning("file_budget", read(policies, "file_budget")) },
    { key: "worktrees", label: "Worktrees", kind: "definition",
      value: meaning("worktrees", read(policies, "worktrees")) },
    { key: "generated_children", label: "Child items", kind: "definition",
      value: meaning("generated_children", read(policies, "generated_children")) },
    { key: "lane_topology", label: "Lane topology", kind: "derived",
      value: topology.value === ABSENT ? null : topology.value },
    { key: "qa", label: "Verification", kind: "posture",
      value: meaning("qa", read(policies, "qa")) },
    { key: "approvals", label: "Approvals",
      kind: (policies.item_posture_allowlist || []).includes("approval_on_done")
        ? "posture" : "definition",
      value: meaning("approvals", read(policies, "approvals")) },
    { key: "delivery", label: "Delivery",
      kind: (policies.item_posture_allowlist || []).includes("deployment")
        ? "posture" : "definition",
      value: meaning("delivery", read(policies, "delivery")) },
    { key: "database_changes", label: "Database changes", kind: "invariant",
      value: "governed migrations on every change" },
  ];
}

function cell(documentNode, row, workflow, onEdit) {
  const host = el(documentNode, "div", `wp-policy-cell wp-${row.kind}`);
  const label = el(documentNode, "div", "workflow-posture-label");
  // Lock means enforced. A description of behavior is not enforced by
  // anything that reads it, so it never wears one.
  if (row.kind !== "derived") {
    label.appendChild(el(documentNode, "span", "workflow-lock", "🔒"));
  }
  label.appendChild(el(documentNode, "span", null, row.label));
  if (row.kind === "derived") {
    label.appendChild(el(documentNode, "span", "wp-derived-tag", "derived"));
  }
  host.appendChild(label);
  host.appendChild(el(
    documentNode,
    "div",
    `workflow-posture-value${row.value ? "" : " wp-predates"}`,
    row.value || "default (predates this version)",
  ));
  if (row.detail) {
    host.appendChild(el(documentNode, "div", "wp-policy-axes", row.detail));
  }
  host.appendChild(el(documentNode, "div", "wp-policy-lever",
    lever(row.kind, workflow, Boolean(onEdit))));
  host.appendChild(el(documentNode, "div", "wp-policy-enforced",
    `Enforced by ${ENFORCED_BY[row.key]}`));
  if (onEdit && (row.kind === "definition" || row.kind === "posture")) {
    const edit = el(documentNode, "button", "workflow-button compact",
      `Edit · publishes v${workflow.current_version + 1}`);
    edit.type = "button";
    edit.addEventListener("click", () => onEdit(row, workflow));
    host.appendChild(edit);
  }
  return host;
}

export function renderPolicyGrid(
  documentNode, host, workflow, policies, onEdit,
) {
  const grid = el(documentNode, "div", "wp-policy-grid");
  for (const row of rows(workflow, policies)) {
    grid.appendChild(cell(documentNode, row, workflow, onEdit));
  }
  host.appendChild(grid);
  return grid;
}

export { rows as policyRows };
