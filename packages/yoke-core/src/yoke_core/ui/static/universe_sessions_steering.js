import { el } from "./universe_view_support.js";

// The wheel marks a steering seat wherever one is shown: the corner of the
// lead box on the seat's own card, and the marker on a steering holding
// row. One wording, so both read as the same fact.
export const STEERING_MARKER_TITLE =
  "steering seat — this session steered this project";

function projectSlug(projects, projectId) {
  const found = (Array.isArray(projects) ? projects : []).find(
    (candidate) => String(candidate.id) === String(projectId),
  );
  return String(found?.slug || found?.name || "").trim();
}

function currentHoldings(row) {
  return Array.isArray(row?.holdings?.current) ? row.holdings.current : [];
}

function steeringClaims(row) {
  return currentHoldings(row).filter(
    (claim) => claim.target_kind === "steering",
  );
}

function claimProjectId(claim) {
  return claim.project_id ?? claim.scope?.project_id;
}

function steeringDocs(claim) {
  return (Array.isArray(claim.strategy_docs) ? claim.strategy_docs : [])
    .map((slug) => String(slug || ""))
    .filter(Boolean);
}

function releasedHoldingKey(holding) {
  if (holding.target_kind === "steering") {
    const documents = [...new Set(steeringDocs(holding))].sort();
    return ["steering", claimProjectId(holding), ...documents].join("\u0000");
  }
  return String(
    holding.target_key
      || `${holding.target_kind || holding.holding_kind}\u0000${holding.target || ""}`,
  );
}

function occurrenceCount(holding) {
  const count = Number(holding.occurrence_count || 1);
  return Number.isFinite(count) && count > 1 ? Math.floor(count) : 1;
}

function releasedAtMillis(holding) {
  const timestamp = Date.parse(String(holding.released_at || ""));
  return Number.isNaN(timestamp) ? Number.NEGATIVE_INFINITY : timestamp;
}

// Keep the card's visible ordering and identity semantics at its render
// boundary, so every caller counts distinct holds rather than claim events.
export function releasedHoldingHistory(entries) {
  const grouped = new Map();
  for (const holding of (Array.isArray(entries) ? entries : [])) {
    const key = releasedHoldingKey(holding);
    const prior = grouped.get(key);
    if (!prior) {
      grouped.set(key, { ...holding, occurrence_count: occurrenceCount(holding) });
      continue;
    }
    const count = occurrenceCount(prior) + occurrenceCount(holding);
    const latest = releasedAtMillis(holding) > releasedAtMillis(prior)
      ? { ...prior, ...holding }
      : { ...prior };
    grouped.set(key, { ...latest, occurrence_count: count });
  }
  return [...grouped.values()]
    .sort((left, right) => Number(right.target_kind === "steering")
      - Number(left.target_kind === "steering"))
    .map((holding) => {
      if (holding.occurrence_count > 1) return holding;
      const single = { ...holding };
      delete single.occurrence_count;
      return single;
    });
}

function steeringScope(claim, projects) {
  const docs = steeringDocs(claim);
  return {
    project: projectSlug(projects, claimProjectId(claim)) || "unknown project",
    docs: docs.length ? docs.join(", ") : "no doc lock",
  };
}

// One document lock, named the way a steering claim names the same one.
// The project is half the key: two projects steered from same-named
// documents are two distinct locks, and folding on the slug alone would
// hide one behind the other.
function documentKey(projectId, slug) {
  return `${String(projectId)}\u0000${String(slug || "")}`;
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

// Which document locks a steering claim among `entries` already names,
// so the seat and its document read as the one hold they are instead of
// two rows saying the same thing. A lock nobody steers from — a document
// held without the seat — is not covered and keeps its own row. Current
// and released holdings fold by the same rule: released steering claims
// carry the documents whose hold windows overlapped theirs, so a seat
// that has been let go still names what it steered from.
export function steeringDocCovers(entries) {
  const covered = new Set();
  for (const claim of (Array.isArray(entries) ? entries : [])) {
    if (claim.target_kind !== "steering") continue;
    for (const slug of steeringDocs(claim)) {
      covered.add(documentKey(claimProjectId(claim), slug));
    }
  }
  if (!covered.size) return () => false;
  return (holding) => holding.holding_kind === "strategy_document"
    && covered.has(documentKey(holding.project_id, holding.strategy_doc));
}

// Which current holdings the steering block above the roster already
// states, so the holdings list can leave them out instead of repeating
// them. The block names every current seat outright, and each seat folds
// in the documents it steers from.
export function steeringLeadCovers(row) {
  const foldsIn = steeringDocCovers(currentHoldings(row));
  return (holding) => holding.target_kind === "steering" || foldsIn(holding);
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
  const wheel = el(documentNode, "span", "session-steering-wheel", "\u{1F6DE}");
  wheel.title = STEERING_MARKER_TITLE;
  wheel.setAttribute("role", "img");
  wheel.setAttribute("aria-label", STEERING_MARKER_TITLE);
  lead.appendChild(wheel);
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
