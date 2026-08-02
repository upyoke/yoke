import { buildUniverseRoute } from "./universe_navigation.js";
import {
  commandPanel,
  detailColumns,
  itemHeading,
  verificationPanel,
} from "./item_view_primitives.js";
import {
  el,
  loadSection,
  section,
  statePill,
} from "./universe_view_support.js";
import { relativeTime } from "./universe_time.js";
import {
  readablePolicyValue,
  workflowPanel,
} from "./workflow_view_primitives.js";

const LANE_STATE_PRESENTATION = {
  active: { tone: "running", label: "active" },
  committed: { tone: "succeeded", label: "slice committed" },
};

function worktreeLanePill(documentNode, state) {
  const value = String(state || "");
  const presentation = LANE_STATE_PRESENTATION[value] || {
    tone: value,
    label: value,
  };
  const pill = statePill(
    documentNode, presentation.tone, presentation.label,
  );
  if (pill) pill.setAttribute("data-state", value);
  return pill;
}

function executionDocumentPanel(documentNode, item, document) {
  const { panel, body } = workflowPanel(documentNode, "Execution document");
  if (!document) {
    body.appendChild(el(
      documentNode, "p", "empty",
      "No execution strategy document is linked.",
    ));
    return panel;
  }
  const card = el(documentNode, "a", "blitz-document");
  card.href = buildUniverseRoute(
    "strategy", String(item.project.id), document.slug,
  );
  card.appendChild(el(documentNode, "span", "blitz-document-icon", "❖"));
  const copy = el(documentNode, "span", "blitz-document-copy");
  copy.appendChild(el(documentNode, "strong", "mono", document.slug));
  const detail = el(documentNode, "span", "item-muted");
  detail.appendChild(el(
    documentNode,
    "span",
    null,
    document.parent_slug
      ? `child of ${document.parent_slug} · revised `
      : "top-level strategy · revised ",
  ));
  if (document.updated_at) {
    detail.appendChild(relativeTime(documentNode, document.updated_at));
  } else {
    detail.appendChild(el(documentNode, "span", null, "recently"));
  }
  copy.appendChild(detail);
  card.appendChild(copy);
  const pill = statePill(
    documentNode,
    document.execution_claim ? "claimed" : "available",
    document.execution_claim ? "🔒 claimed" : "available",
  );
  if (pill) card.appendChild(pill);
  body.appendChild(card);
  return panel;
}

function worktreeLanesPanel(documentNode, item) {
  const panel = section(
    documentNode, "Worktree lanes", { showRaw: false },
  );
  const rows = item.worktrees || [];
  panel.setCount(rows.length);
  panel.renderEnvelope(
    {
      status: 200,
      envelope: { success: true, result: { worktree_lanes: rows } },
    },
    (body) => {
      if (!rows.length) {
        body.appendChild(el(
          documentNode, "p", "empty", "No worktree lanes registered.",
        ));
        return;
      }
      const wrap = el(documentNode, "div", "table-wrap");
      const table = el(documentNode, "table", "items");
      const head = el(documentNode, "tr");
      for (const label of ["Role", "Branch", "State"]) {
        head.appendChild(el(documentNode, "th", null, label));
      }
      table.appendChild(head);
      for (const row of rows) {
        const tr = el(documentNode, "tr");
        const role = el(documentNode, "td");
        role.appendChild(el(
          documentNode, "span", "item-workflow", row.lane_role,
        ));
        tr.appendChild(role);
        tr.appendChild(el(
          documentNode, "td", "mono item-muted", row.branch,
        ));
        const state = el(documentNode, "td");
        const pill = worktreeLanePill(documentNode, row.state);
        if (pill) state.appendChild(pill);
        tr.appendChild(state);
        table.appendChild(tr);
      }
      wrap.appendChild(table);
      body.appendChild(wrap);
    },
  );
  return panel;
}

function blitzFactsPanel(documentNode, item) {
  const { panel, body } = workflowPanel(documentNode, "Item details");
  const table = el(documentNode, "table", "items kv item-facts");
  const claim = item.claim;
  const pathClaims = item.path_claims || { total: 0 };
  const fileBudget = item.file_budget || { total: 0, paths: [] };
  const effectivePolicies = item.workflow.effective_policies || {};
  const workflow = el(documentNode, "span", "item-inline");
  workflow.appendChild(el(
    documentNode,
    "span",
    "item-workflow",
    String(item.workflow.id || "blitz").toLowerCase(),
  ));
  workflow.appendChild(el(
    documentNode, "span", "item-version", `v${item.workflow.version}`,
  ));
  const liveClaim = claim
    ? el(documentNode, "span", "item-inline")
    : "none";
  if (claim) {
    liveClaim.appendChild(el(
      documentNode, "span", null, claim.actor_label || claim.session_id,
    ));
    if (
      claim.session_id &&
      claim.session_id !== (claim.actor_label || claim.session_id)
    ) {
      liveClaim.appendChild(el(documentNode, "span", "item-muted", "·"));
      liveClaim.appendChild(el(
        documentNode, "span", "mono", claim.session_id,
      ));
    }
  }
  const claimStates = Object.entries(pathClaims.states || {})
    .map(([state, count]) => `${count} ${state}`)
    .join(" · ");
  const values = [
    ["Project", item.project.name || item.project.slug],
    ["Workflow", workflow],
    [
      "Status",
      statePill(
        documentNode,
        item.status,
        item.workflow.stage_label || item.status,
      ),
    ],
    ["Owner", item.owner || "unassigned"],
    ["Live claim", liveClaim],
    [
      "File budget",
      fileBudget.total
        ? `${fileBudget.total} ${fileBudget.total === 1 ? "file" : "files"}`
        : effectivePolicies.file_budget === "optional"
          ? "none · workflow default"
          : "none recorded",
    ],
    [
      "Path claims",
      pathClaims.total
        ? `${pathClaims.total} registered${claimStates ? ` · ${claimStates}` : ""}`
        : effectivePolicies.path_claims === "optional"
          ? "none · workflow default"
          : "none",
    ],
    [
      "Created",
      item.created_at ? relativeTime(documentNode, item.created_at) : "",
    ],
  ];
  for (const [label, value] of values) {
    const row = el(documentNode, "tr");
    row.appendChild(el(documentNode, "th", null, label));
    const cell = el(documentNode, "td");
    if (value && value.tagName) cell.appendChild(value);
    else cell.textContent = String(value);
    row.appendChild(cell);
    table.appendChild(row);
  }
  body.appendChild(table);
  return panel;
}

function postureCell(documentNode, label, value, locked = false) {
  const cell = el(
    documentNode, "div", `item-posture-cell${locked ? " locked" : ""}`,
  );
  cell.appendChild(el(
    documentNode, "div", "item-posture-label", label,
  ));
  cell.appendChild(el(
    documentNode, "div", "item-posture-value", value,
  ));
  return cell;
}

function blitzPosturePanel(documentNode, item) {
  const { panel, body } = workflowPanel(documentNode, "Execution posture");
  const grid = el(documentNode, "div", "item-posture-grid");
  const lanes = item.worktrees || [];
  const effectivePolicies = item.workflow.effective_policies || {};
  grid.appendChild(postureCell(documentNode, "Child items", "none"));
  for (const [label, key] of [
    ["File Budget", "file_budget"],
    ["Path survey", "path_survey"],
    ["Path claims", "path_claims"],
  ]) {
    if (effectivePolicies[key] === undefined) continue;
    grid.appendChild(postureCell(
      documentNode, label, readablePolicyValue(key, effectivePolicies[key]),
    ));
  }
  grid.appendChild(postureCell(
    documentNode,
    "Parallelism",
    lanes.length ? `${lanes.length} lanes` : "ready for worker lanes",
  ));
  grid.appendChild(postureCell(
    documentNode,
    "Integration",
    "main session",
  ));
  grid.appendChild(postureCell(
    documentNode, "Migrations", "governed", true,
  ));
  body.appendChild(grid);
  return panel;
}

function renderLoadedBlitz(context, main, item, execution) {
  const documentNode = context.document;
  const host = el(documentNode, "div", "item-detail blitz-detail");
  host.appendChild(itemHeading(documentNode, item));
  host.appendChild(detailColumns(
    documentNode,
    [
      executionDocumentPanel(
        documentNode, item, execution.execution_document,
      ),
      worktreeLanesPanel(documentNode, item),
      verificationPanel(documentNode, item),
    ],
    [
      blitzFactsPanel(documentNode, item),
      blitzPosturePanel(documentNode, item),
      commandPanel(documentNode, item),
    ],
  ));
  main.replaceChildren(host);
}

export function renderBlitzItemDetail(context, main, item) {
  const loading = section(context.document, "Execution document");
  main.replaceChildren(loading);
  loadSection(
    context,
    loading,
    "strategy.execution.get",
    {},
    (_body, callResult) => {
      renderLoadedBlitz(
        context,
        main,
        item,
        (callResult.envelope.result || {}).execution || {},
      );
    },
    {
      kind: "item",
      item_ref: item.public_ref,
      project_id: String(item.project.id),
    },
  );
}
