import { el } from "./universe_view_support.js";

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

function claimProjectId(claim) {
  return claim.project_id ?? claim.scope?.project_id;
}

function steeringScope(claim, projects) {
  const docs = (Array.isArray(claim.strategy_docs) ? claim.strategy_docs : [])
    .map((slug) => String(slug || ""))
    .filter(Boolean);
  return {
    project: projectSlug(projects, claimProjectId(claim)) || "unknown project",
    docs: docs.length ? docs.join(", ") : "no doc lock",
  };
}

export function steeringHoldingText(claim, projects = []) {
  const scope = steeringScope(claim, projects);
  return `${scope.project} · ${scope.docs}`;
}

// Every project this session steers, each beside the documents it steers
// THAT project from. Current holdings are the authority — a session
// steering three projects holds three claim targets. Pairing each project
// with its own documents is also what keeps two projects steering from
// same-named documents readable as two holds: the projects differ even
// where the slugs do not.
function steeringScopes(row, projects) {
  return steeringClaims(row).map((claim) => steeringScope(claim, projects));
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
// item ref. Other cards do not annotate a relationship to that seat.
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
