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

let sparkFillSequence = 0;

function svgElement(documentNode, name) {
  if (typeof documentNode.createElementNS === "function") {
    return documentNode.createElementNS("http://www.w3.org/2000/svg", name);
  }
  return documentNode.createElement(name);
}

function strategySpark(documentNode, days) {
  const width = 240;
  const height = 34;
  const values = days.map((row) => row.writes);
  const maximum = Math.max(...values);
  const minimum = Math.min(...values);
  const range = maximum - minimum || 1;
  const x = (index) => index / Math.max(values.length - 1, 1) * width;
  const y = (value) => height - ((value - minimum) / range) * (height - 4) - 2;
  const points = values.map(
    (value, index) => `${x(index).toFixed(1)},${y(value).toFixed(1)}`,
  ).join(" ");
  const fillId = `strategy-spark-fill-${sparkFillSequence += 1}`;
  const spark = svgElement(documentNode, "svg");
  spark.setAttribute("class", "strategy-spark");
  if (typeof spark.className === "string") spark.className = "strategy-spark";
  spark.setAttribute("viewBox", `0 0 ${width} ${height}`);
  spark.setAttribute("preserveAspectRatio", "none");
  spark.setAttribute("role", "img");
  spark.setAttribute("aria-label", "Strategy document writes over 120 days");
  const defs = svgElement(documentNode, "defs");
  const gradient = svgElement(documentNode, "linearGradient");
  gradient.setAttribute("id", fillId);
  gradient.setAttribute("x1", "0");
  gradient.setAttribute("x2", "0");
  gradient.setAttribute("y1", "0");
  gradient.setAttribute("y2", "1");
  const top = svgElement(documentNode, "stop");
  top.setAttribute("offset", "0");
  top.setAttribute("stop-color", "var(--yoke-good)");
  top.setAttribute("stop-opacity", ".22");
  gradient.appendChild(top);
  const bottom = svgElement(documentNode, "stop");
  bottom.setAttribute("offset", "1");
  bottom.setAttribute("stop-color", "var(--yoke-good)");
  bottom.setAttribute("stop-opacity", "0");
  gradient.appendChild(bottom);
  defs.appendChild(gradient);
  spark.appendChild(defs);
  const area = svgElement(documentNode, "polygon");
  area.setAttribute(
    "points",
    `0,${height} ${points} ${width},${height}`,
  );
  area.setAttribute("fill", `url(#${fillId})`);
  spark.appendChild(area);
  const line = svgElement(documentNode, "polyline");
  line.setAttribute("points", points);
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", "var(--yoke-good)");
  line.setAttribute("stroke-width", "1.6");
  line.setAttribute("stroke-linejoin", "round");
  line.setAttribute("stroke-linecap", "round");
  line.setAttribute("vector-effect", "non-scaling-stroke");
  spark.appendChild(line);
  return spark;
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
  const label = el(documentNode, "div", "strategy-spark-label");
  label.appendChild(el(documentNode, "span", null, "Strategy-doc writes"));
  label.appendChild(el(
    documentNode,
    "strong",
    null,
    `${days.slice(-7).reduce((sum, row) => sum + row.writes, 0)} this week`,
  ));
  body.appendChild(label);
  body.appendChild(strategySpark(documentNode, days));
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
  const link = el(documentNode, "a", "row-link mono", `${label} →`);
  link.href = buildUniverseRoute("strategy", String(projectId), slug);
  return link;
}

function executionFact(documentNode, projectId, claim) {
  if (!claim) return "available";
  const host = el(documentNode, "span", "strategy-inline");
  const pill = statePill(documentNode, "item-owned");
  if (pill) host.appendChild(pill);
  host.appendChild(el(documentNode, "span", "item-muted", "·"));
  const link = el(
    documentNode,
    "a",
    "row-link mono",
    `${claim.item_ref || `item ${claim.owning_item_id}`} →`,
  );
  link.href = buildUniverseRoute(
    "items", String(projectId), claim.item_ref || String(claim.owning_item_id),
  );
  host.appendChild(link);
  const workflowId = String(claim.workflow_id || "").trim();
  const workflowName = workflowId
    ? `${workflowId[0].toUpperCase()}${workflowId.slice(1)}`
    : "workflow";
  const workflowVersion = claim.workflow_version_id;
  host.appendChild(el(
    documentNode,
    "span",
    "item-muted",
    `${workflowName}${workflowVersion ? ` v${workflowVersion}` : ""}`,
  ));
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
  const pendingCount = Number(
    doc.pending_review_count ??
      (doc.review_requests || []).filter(
        (request) => request.status === "pending",
      ).length,
  );
  const approval = el(documentNode, "span", "strategy-inline");
  const reviewPill = statePill(
    documentNode,
    pending ? "pending" : "idle",
    pending
      ? `${pendingCount} ${
        pendingCount === 1 ? "review" : "reviews"
      } requested`
      : "no review requested",
  );
  if (reviewPill) approval.appendChild(reviewPill);
  if (pending) {
    const feedback = el(
      documentNode, "span", "strategy-approval-feedback error",
    );
    feedback.setAttribute("role", "alert");
    feedback.hidden = true;
    const approve = button(
      documentNode,
      `Approve revision ${doc.current_revision}`,
      "item-action primary",
    );
    approve.addEventListener("click", async () => {
      approve.disabled = true;
      feedback.hidden = true;
      try {
        const result = await callFunction(
          context.client,
          "decision_requests.resolve",
          { request_id: Number(pending.id), action: "approve" },
          { kind: "global", project_id: String(projectId) },
        );
        if (result.status === 200 && result.envelope.success) {
          refresh();
          return;
        }
        feedback.textContent =
          result.envelope.error?.message || "Approval failed.";
      } catch (error) {
        feedback.textContent = `Approval failed: ${String(error)}`;
      }
      feedback.hidden = false;
      approve.disabled = false;
    });
    approval.appendChild(approve);
    approval.appendChild(feedback);
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
