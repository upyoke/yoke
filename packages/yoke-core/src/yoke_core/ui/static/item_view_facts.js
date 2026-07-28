import { buildUniverseRoute } from "./universe_navigation.js";
import { relativeTime } from "./universe_time.js";
import {
  el,
  statePill,
} from "./universe_view_support.js";
import {
  readablePolicyValue,
  workflowPanel,
} from "./workflow_view_primitives.js";

function appendFact(documentNode, table, label, value, className = null) {
  const row = el(documentNode, "tr");
  row.appendChild(el(documentNode, "th", null, label));
  const cell = el(documentNode, "td", className);
  if (value && value.tagName) cell.appendChild(value);
  else cell.textContent = String(value ?? "");
  row.appendChild(cell);
  table.appendChild(row);
}

function workflowFact(documentNode, item) {
  const host = el(documentNode, "span", "item-inline");
  const link = el(
    documentNode,
    "a",
    "row-link item-workflow-link",
    `${item.workflow.name || item.workflow.id} →`,
  );
  link.href = buildUniverseRoute(
    "workflows", null, String(item.workflow.id),
  );
  host.appendChild(link);
  host.appendChild(el(
    documentNode,
    "span",
    "item-version",
    `v${item.workflow.version}`,
  ));
  return host;
}

function statusFact(documentNode, item) {
  return statePill(
    documentNode,
    item.status,
    item.workflow.stage_label || item.status,
  );
}

function claimFact(documentNode, claim) {
  if (!claim) return "none";
  const host = el(documentNode, "span", "item-inline");
  host.appendChild(el(documentNode, "span", "item-fact-lock", "🔒"));
  host.appendChild(el(
    documentNode,
    "span",
    "mono",
    claim.actor_label || claim.session_id,
  ));
  return host;
}

function worktreeFact(documentNode, item) {
  const lane = (item.worktrees || []).find((row) => row.state === "active") ||
    (item.worktrees || [])[0];
  return lane
    ? el(documentNode, "span", "mono item-muted", lane.branch)
    : "none";
}

function fileBudgetFact(documentNode, item) {
  const budget = item.file_budget || { total: 0, paths: [] };
  const policy = item.workflow?.policies?.file_budget;
  const tightened = item.workflow?.item_posture?.file_budget === true;
  if (!Number(budget.total)) {
    if (policy === "required_per_task") return "per task";
    if (policy === "optional" && !tightened) return "none · workflow default";
    return "none recorded";
  }
  const label = `${budget.total} ${Number(budget.total) === 1 ? "file" : "files"}`;
  const value = el(documentNode, "span", null, label);
  if (Array.isArray(budget.paths) && budget.paths.length) {
    value.title = budget.paths.join("\n");
  }
  return value;
}

function pathClaimsFact(item) {
  const claims = item.path_claims || { total: 0, states: {} };
  const policy = item.workflow?.policies?.path_claims;
  const tightened = item.workflow?.item_posture?.path_claims === true;
  if (!Number(claims.total)) {
    if (policy === "required_per_task") return "per task";
    if (policy === "optional" && !tightened) return "none · workflow default";
    return "none";
  }
  const states = Object.entries(claims.states || {})
    .map(([state, count]) => `${count} ${state}`)
    .join(" · ");
  return `${claims.total} registered${states ? ` · ${states}` : ""}`;
}

export function factsPanel(documentNode, item) {
  const { panel, body } = workflowPanel(documentNode, "Item details");
  const table = el(documentNode, "table", "items kv item-facts");
  appendFact(
    documentNode, table, "Project", item.project.name || item.project.slug,
  );
  appendFact(documentNode, table, "Workflow", workflowFact(documentNode, item));
  appendFact(documentNode, table, "Status", statusFact(documentNode, item));
  appendFact(documentNode, table, "Owner", item.owner || "unassigned");
  const workflowId = String(item.workflow.id || "").toLowerCase();
  if (workflowId !== "epic") {
    appendFact(documentNode, table, "Claim", claimFact(documentNode, item.claim));
  }
  if (
    item.workflow?.policies?.file_budget !== undefined ||
    Number(item.file_budget?.total)
  ) {
    appendFact(
      documentNode,
      table,
      "File budget",
      fileBudgetFact(documentNode, item),
    );
  }
  if (
    item.workflow?.policies?.path_claims !== undefined ||
    Number(item.path_claims?.total)
  ) {
    appendFact(
      documentNode,
      table,
      "Path claims",
      pathClaimsFact(item),
    );
  }
  if (!["epic", "blitz"].includes(workflowId)) {
    appendFact(documentNode, table, "Worktree", worktreeFact(documentNode, item));
  }
  appendFact(
    documentNode,
    table,
    "Created",
    item.created_at ? relativeTime(documentNode, item.created_at) : "",
  );
  body.appendChild(table);
  return panel;
}

const POSTURE_LABELS = {
  file_budget: "File Budget",
  path_claims: "Path claims",
  worktrees: "Worktrees",
  parallelism: "Parallelism",
  generated_children: "Child items",
};

export function posturePanel(documentNode, item) {
  const { panel, body } = workflowPanel(documentNode, "Execution posture");
  const grid = el(documentNode, "div", "item-posture-grid");
  const policies = item.workflow.policies || {};
  const itemPosture = item.workflow.item_posture || {};
  const workflowId = String(item.workflow.id || "").toLowerCase();
  const preferredKeys = workflowId === "dash"
    ? ["generated_children", "file_budget", "path_claims", "worktrees"]
    : ["file_budget", "path_claims", "worktrees", "parallelism"];
  const keys = preferredKeys.filter((key) => policies[key] !== undefined);
  for (const key of keys) {
    const cell = el(documentNode, "div", "item-posture-cell");
    cell.appendChild(el(
      documentNode, "div", "item-posture-label", POSTURE_LABELS[key],
    ));
    cell.appendChild(el(
      documentNode,
      "div",
      "item-posture-value",
      itemPostureValue(
        workflowId,
        key,
        ["file_budget", "path_claims"].includes(key) && itemPosture[key]
          ? "required"
          : policies[key],
      ),
    ));
    grid.appendChild(cell);
  }
  const invariant = el(documentNode, "div", "item-posture-cell locked");
  invariant.appendChild(el(
    documentNode, "div", "item-posture-label", "Migrations",
  ));
  invariant.appendChild(el(
    documentNode, "div", "item-posture-value", "governed",
  ));
  grid.appendChild(invariant);
  body.appendChild(grid);
  return panel;
}

function itemPostureValue(workflowId, key, value) {
  if (workflowId === "dash" && key === "worktrees") return "one";
  return readablePolicyValue(key, value);
}
