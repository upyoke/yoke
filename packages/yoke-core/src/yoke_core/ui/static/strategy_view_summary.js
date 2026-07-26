import { buildUniverseRoute } from "./universe_navigation.js";
import {
  callFunction,
  el,
  statePill,
} from "./universe_view_support.js";
import {
  button,
  workflowPanel,
} from "./workflow_view_primitives.js";

function stat(documentNode, value, label) {
  const node = el(documentNode, "div", "stat");
  node.appendChild(el(documentNode, "div", "n", String(value)));
  node.appendChild(el(documentNode, "div", "l", label));
  return node;
}

export function strategyStats(documentNode, docs) {
  const host = el(documentNode, "div", "stat-row strategy-stats");
  host.appendChild(stat(documentNode, docs.length, "docs"));
  host.appendChild(stat(
    documentNode,
    docs.reduce((total, doc) => total + Number(doc.recent_writes || 0), 0),
    "writes this week",
  ));
  host.appendChild(stat(
    documentNode,
    docs.filter((doc) => doc.execution_state === "claimed").length,
    "claimed for execution",
  ));
  host.appendChild(stat(
    documentNode,
    docs.filter((doc) => doc.archived).length,
    "archived",
  ));
  return host;
}

export function strategyReviewCallout(documentNode) {
  const callout = el(documentNode, "div", "strategy-callout");
  callout.appendChild(el(documentNode, "span", "strategy-callout-icon", "⌘"));
  callout.appendChild(el(
    documentNode,
    "span",
    null,
    "Review and approve here. Author documents in your harness.",
  ));
  return callout;
}

function dateKey(date) {
  return date.toISOString().slice(0, 10);
}

export function strategyWriteActivity(documentNode, writes) {
  const { panel, body } = workflowPanel(
    documentNode, "Writes", { detail: "last 120 days" },
  );
  const counts = new Map();
  for (const row of writes) {
    counts.set(
      String(row.day),
      Number(counts.get(String(row.day)) || 0) + Number(row.writes || 0),
    );
  }
  const today = new Date();
  const days = [];
  for (let offset = 119; offset >= 0; offset -= 1) {
    const day = new Date(today);
    day.setUTCDate(today.getUTCDate() - offset);
    const key = dateKey(day);
    days.push({ day: key, writes: counts.get(key) || 0 });
  }
  const maximum = Math.max(1, ...days.map((row) => row.writes));
  const label = el(documentNode, "div", "strategy-spark-label");
  label.appendChild(el(documentNode, "span", null, "Strategy-doc writes"));
  label.appendChild(el(
    documentNode,
    "strong",
    null,
    `${days.slice(-7).reduce((sum, row) => sum + row.writes, 0)} this week`,
  ));
  body.appendChild(label);
  const spark = el(documentNode, "div", "strategy-spark");
  for (const row of days) {
    const bar = el(documentNode, "span", "strategy-spark-bar");
    bar.style.height = `${Math.max(2, (row.writes / maximum) * 100)}%`;
    bar.title = `${row.day} · ${row.writes} writes`;
    spark.appendChild(bar);
  }
  body.appendChild(spark);
  return panel;
}

function factRow(documentNode, label, value) {
  const row = el(documentNode, "tr");
  row.appendChild(el(documentNode, "th", null, label));
  const cell = el(documentNode, "td");
  if (value && value.tagName) cell.appendChild(value);
  else cell.textContent = String(value ?? "");
  row.appendChild(cell);
  return row;
}

function docLink(documentNode, projectId, slug, label = slug) {
  const link = el(documentNode, "a", "row-link mono", label);
  link.href = buildUniverseRoute("strategy", String(projectId), slug);
  return link;
}

function executionFact(documentNode, projectId, claim) {
  if (!claim) return "available";
  const host = el(documentNode, "span", "strategy-inline");
  const pill = statePill(documentNode, "item-owned");
  if (pill) host.appendChild(pill);
  const link = el(
    documentNode,
    "a",
    "row-link mono",
    claim.item_ref || `item ${claim.owning_item_id}`,
  );
  link.href = buildUniverseRoute(
    "items", String(projectId), claim.item_ref || String(claim.owning_item_id),
  );
  host.appendChild(link);
  host.appendChild(el(documentNode, "span", "item-muted", "Blitz"));
  return host;
}

export function stateActionsPanel(
  context,
  projectId,
  doc,
  refresh,
) {
  const documentNode = context.document;
  const { panel, body } = workflowPanel(documentNode, "State & actions");
  const table = el(documentNode, "table", "items kv strategy-state");
  table.appendChild(factRow(
    documentNode,
    "Claim",
    executionFact(documentNode, projectId, doc.execution_claim),
  ));

  const pending = (doc.review_requests || []).find(
    (request) => request.status === "pending",
  );
  const approval = el(documentNode, "span", "strategy-inline");
  const reviewPill = statePill(
    documentNode,
    pending ? `${doc.pending_review_count} review requested` : "no review requested",
  );
  if (reviewPill) approval.appendChild(reviewPill);
  if (pending) {
    const approve = button(
      documentNode,
      `Approve revision ${doc.current_revision}`,
      "item-action primary",
    );
    approve.addEventListener("click", async () => {
      approve.disabled = true;
      const result = await callFunction(
        context.client,
        "decision_requests.resolve",
        { request_id: Number(pending.id), action: "approve" },
        { kind: "global", project_id: String(projectId) },
      );
      if (result.status === 200 && result.envelope.success) refresh();
      else approve.disabled = false;
    });
    approval.appendChild(approve);
  }
  table.appendChild(factRow(documentNode, "Approval", approval));
  table.appendChild(factRow(
    documentNode,
    "Parent",
    doc.parent_slug
      ? docLink(documentNode, projectId, doc.parent_slug)
      : "top-level strategy",
  ));
  const references = el(documentNode, "span", "strategy-inline");
  for (const reference of doc.references || []) {
    references.appendChild(docLink(documentNode, projectId, reference));
  }
  table.appendChild(factRow(
    documentNode,
    "References",
    references.children.length ? references : "none",
  ));
  table.appendChild(factRow(
    documentNode, "Last editor", doc.updated_by || "unattributed",
  ));
  body.replaceChildren(table);
  return panel;
}
