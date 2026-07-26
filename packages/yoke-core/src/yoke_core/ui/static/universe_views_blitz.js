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
  renderTable,
  section,
  statePill,
} from "./universe_view_support.js";
import {
  formatTimestamp,
  workflowPanel,
} from "./workflow_view_primitives.js";

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
  copy.appendChild(el(
    documentNode,
    "span",
    "item-muted",
    [
      document.parent_slug ? `child of ${document.parent_slug}` : "top-level strategy",
      `revised ${formatTimestamp(document.updated_at)}`,
    ].join(" · "),
  ));
  card.appendChild(copy);
  const pill = statePill(
    documentNode, document.execution_claim ? "claimed" : "available",
  );
  if (pill) card.appendChild(pill);
  body.appendChild(card);
  return panel;
}

function worktreeLanesPanel(documentNode, item) {
  const panel = section(documentNode, "Worktree lanes");
  const rows = item.worktrees || [];
  panel.setCount(rows.length);
  panel.renderEnvelope(
    {
      status: 200,
      envelope: { success: true, result: { worktree_lanes: rows } },
    },
    (body) => renderTable(body, rows, [
      { label: "Role", value: (row) => row.lane_role },
      { label: "Branch", value: (row) => row.branch, mono: true },
      { label: "State", value: (row) => row.state, pill: true },
    ], "No worktree lanes registered."),
  );
  return panel;
}

function blitzFactsPanel(documentNode, item) {
  const { panel, body } = workflowPanel(documentNode, "Item details");
  const table = el(documentNode, "table", "items kv item-facts");
  const claim = item.claim;
  const pathClaims = item.path_claims || { total: 0 };
  const values = [
    ["Project", item.project.name || item.project.slug],
    ["Workflow", `${item.workflow.name || "Blitz"} · v${item.workflow.version}`],
    ["Status", item.workflow.stage_label || item.status],
    ["Owner", item.owner || "unassigned"],
    [
      "Live claim",
      claim
        ? `${claim.actor_label || claim.session_id} · ${claim.session_id}`
        : "none",
    ],
    [
      "Path claims",
      pathClaims.total
        ? `${pathClaims.total} registered`
        : "none · workflow default",
    ],
    ["Created", formatTimestamp(item.created_at)],
  ];
  for (const [label, value] of values) {
    const row = el(documentNode, "tr");
    row.appendChild(el(documentNode, "th", null, label));
    row.appendChild(el(documentNode, "td", null, String(value)));
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
  const active = (item.worktrees || []).filter((row) => row.state === "active");
  const integration = active.find((row) => row.lane_role === "integration");
  grid.appendChild(postureCell(documentNode, "Child items", "none"));
  grid.appendChild(postureCell(
    documentNode,
    "Parallelism",
    active.length ? `${active.length} lanes` : "ready for worker lanes",
  ));
  grid.appendChild(postureCell(
    documentNode,
    "Integration",
    integration ? "integration lane" : "main session",
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
