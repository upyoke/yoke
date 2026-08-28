import { relativeAge } from "./universe_time.js";
import { el } from "./universe_view_support.js";

const REPORT_STATES = new Set([
  "sent", "acknowledged", "cancelled", "expired", "unknown",
]);

function projectSlug(projects, projectId) {
  const found = (Array.isArray(projects) ? projects : []).find(
    (candidate) => String(candidate.id) === String(projectId),
  );
  return String(found?.slug || found?.name || "").trim();
}

function steeringClaims(row) {
  return (Array.isArray(row?.holdings?.current) ? row.holdings.current : []).filter(
    (claim) => claim.target_kind === "steering",
  );
}

function strategyDocs(row, projectId) {
  return (Array.isArray(row?.holdings?.current) ? row.holdings.current : [])
    .filter(
      (holding) => holding.holding_kind === "strategy_document"
        && String(holding.project_id) === String(projectId),
    )
    .map((holding) => String(holding.strategy_doc || ""))
    .filter(Boolean);
}

function claimProjectId(claim) {
  return claim.project_id ?? claim.scope?.project_id;
}

// Every project this session steers, each beside the documents it steers
// THAT project from. Current holdings are the authority — a session
// steering three projects holds three claim targets. Pairing each project
// with its own documents is also what keeps two projects steering from
// same-named documents readable as two holds: the projects differ even
// where the slugs do not.
function steeringScopes(row, projects) {
  return steeringClaims(row).map((claim) => {
    const docs = strategyDocs(row, claimProjectId(claim));
    return {
      project: projectSlug(projects, claimProjectId(claim)) || "unknown project",
      docs: docs.length ? docs.join(", ") : "all docs",
    };
  });
}

// Which current holdings the steering block above the roster already
// states, so the holdings list can leave them out instead of repeating
// them. A document lock on a project this session does not steer is not
// covered — it belongs in the ordinary holdings.
export function steeringLeadCovers(row) {
  const steered = new Set(
    steeringClaims(row).map((claim) => String(claimProjectId(claim))),
  );
  if (!steered.size) return () => false;
  return (holding) => holding.target_kind === "steering"
    || (holding.holding_kind === "strategy_document"
      && steered.has(String(holding.project_id)));
}

// A steering seat holds no item; its scope IS its work, so on its card the
// scope leads the body where a worker card leads with its claim. Reading a
// steering card, the first question is which projects this seat drives and
// from which documents — the same question a worker card answers with an
// item ref.
export function appendSteeringHoldings(documentNode, body, row, projects = []) {
  const scopes = steeringScopes(row, projects);
  if (!scopes.length) return false;
  const lead = el(documentNode, "div", "session-steering-lead");
  lead.appendChild(el(
    documentNode, "div", "session-steering-lead-label", "Steering",
  ));
  for (const scope of scopes) {
    const line = el(documentNode, "div", "session-steering-scope");
    line.appendChild(el(
      documentNode, "span", "session-steering-project", scope.project,
    ));
    line.appendChild(el(
      documentNode, "span", "session-steering-docs", scope.docs,
    ));
    lead.appendChild(line);
  }
  body.appendChild(lead);
  return true;
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

// The relationships a session has to steering it does not hold. The holder
// case is not here: that is a holding, and it leads the card body through
// appendSteeringHoldings rather than trailing it as an annotation.
export function appendSteeringContext(documentNode, body, row) {
  if (row.steering_parent) {
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
      "Steering coverage",
      `${row.steering_coverage.project || "project"} · held by `
        + `${row.steering_coverage.holder_session_id || "unknown holder"}`,
    );
  }
  appendReport(documentNode, body, row.steering_report);
}

function groupParent(row, bySession) {
  const parentId = String(row.steering_parent?.session_id || "");
  const parent = bySession.get(parentId);
  return parentId && steeringClaims(parent).length ? parentId : "";
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
