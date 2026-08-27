import { relativeAge } from "./universe_time.js";
import { el } from "./universe_view_support.js";

const REPORT_STATES = new Set([
  "sent", "acknowledged", "cancelled", "expired", "unknown",
]);

function scopeText(scope) {
  const project = String(scope?.project || "project not reported");
  const docs = Array.isArray(scope?.strategy_docs) ? scope.strategy_docs : [];
  return `${project} · ${docs.length ? docs.join(", ") : "all docs"}`;
}

function appendContext(documentNode, body, tone, label, detail) {
  const context = el(documentNode, "div", "session-steering-context");
  context.appendChild(el(
    documentNode,
    "span",
    `session-steering-badge is-${tone}`,
    label,
  ));
  context.appendChild(el(documentNode, "span", "session-steering-detail", detail));
  body.appendChild(context);
}

function reportCustody(report) {
  const state = String(report?.recipient_state || "unknown").toLowerCase();
  if (state === "acknowledged") return "acknowledged";
  if (state === "pending" || state === "injected") return "sent";
  return REPORT_STATES.has(state) ? state : "unknown";
}

function appendReport(documentNode, body, report) {
  if (!report) return;
  const custody = reportCustody(report);
  const timestamp = custody === "acknowledged"
    ? report.acknowledged_at || report.created_at
    : report.created_at;
  const line = el(documentNode, "div", "session-steering-report");
  line.appendChild(el(documentNode, "span", null, "Steering report"));
  line.appendChild(el(
    documentNode,
    "span",
    `session-steering-report-badge is-${custody}`,
    `${custody} · ${relativeAge(timestamp)}`,
  ));
  line.appendChild(el(
    documentNode,
    "span",
    "session-steering-report-recipient",
    `to ${report.recipient_session_id || "holder not reported"}`,
  ));
  body.appendChild(line);
}

export function appendSteeringContext(documentNode, body, row) {
  if (row.steering_scope) {
    appendContext(
      documentNode, body, "holder", "Steering", scopeText(row.steering_scope),
    );
  } else if (row.steering_parent) {
    appendContext(
      documentNode,
      body,
      "worker",
      "Steering worker",
      `launched by ${row.steering_parent.session_id || "unknown holder"}`,
    );
  } else if (row.steering_coverage) {
    appendContext(
      documentNode,
      body,
      "covered",
      "Steering scope",
      `${row.steering_coverage.project || "project"} · held by `
        + `${row.steering_coverage.holder_session_id || "unknown holder"}`,
    );
  }
  appendReport(documentNode, body, row.steering_report);
}

function groupParent(row, bySession) {
  const parentId = String(row.steering_parent?.session_id || "");
  const parent = bySession.get(parentId);
  return parentId && parent?.steering_scope ? parentId : "";
}

export function appendSteeringGroups(documentNode, grid, rows, cardFor) {
  const bySession = new Map(rows.map((row) => [String(row.session_id || ""), row]));
  const workers = new Map();
  for (const row of rows) {
    const parentId = groupParent(row, bySession);
    if (!parentId) continue;
    if (!workers.has(parentId)) workers.set(parentId, []);
    workers.get(parentId).push(row);
  }
  const nested = new Set([...workers.values()].flat().map(
    (row) => String(row.session_id || ""),
  ));
  for (const row of rows) {
    const sessionId = String(row.session_id || "");
    if (nested.has(sessionId)) continue;
    const children = workers.get(sessionId) || [];
    if (!children.length) {
      grid.appendChild(cardFor(row));
      continue;
    }
    const group = el(documentNode, "section", "session-steering-group");
    group.setAttribute("data-steering-holder", sessionId);
    group.appendChild(cardFor(row));
    const cluster = el(documentNode, "div", "session-steering-workers");
    cluster.appendChild(el(
      documentNode,
      "h3",
      "session-steering-workers-title",
      `Steering workers (${children.length})`,
    ));
    const childGrid = el(documentNode, "div", "session-steering-worker-grid");
    for (const child of children) childGrid.appendChild(cardFor(child));
    cluster.appendChild(childGrid);
    group.appendChild(cluster);
    grid.appendChild(group);
  }
}
