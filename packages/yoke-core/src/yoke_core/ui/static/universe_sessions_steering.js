import { attachTooltip } from "./universe_tooltip.js";
import { el } from "./universe_view_support.js";

// The symbol marks a steering seat wherever one is shown: the corner of the
// lead box on the seat's own card, and the marker on a steering holding
// row. One wording, so both read as the same fact.
export const STEERING_MARKER_TITLE =
  "steering seat — this session steered this project";

const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
const STEERING_CONNECTOR_PATH = "M 112.41 106.36 L 112.54 103.77 L 112.94 100.88 L 113.59 97.78 L 114.56 94.72 L 115.72 92.11 L 117.41 89.52 L 118.03 88.72 L 120.27 86.24 L 123.20 83.29 L 124.39 82.25 L 125.10 81.71 L 151.80 64.19 L 152.89 63.33 L 153.86 62.22 L 154.59 60.94 L 154.97 59.92 L 155.20 58.82 L 155.24 57.34 L 155.00 55.89 L 154.64 54.87 L 153.93 53.58 L 152.98 52.45 L 151.82 51.54 L 150.83 50.99 L 149.82 50.62 L 148.71 50.39 L 147.63 50.33 L 146.50 50.43 L 145.45 50.69 L 144.40 51.11 L 143.54 51.60 L 108.73 74.46 L 107.53 75.09 L 106.89 75.31 L 106.24 75.47 L 104.89 75.60 L 103.54 75.47 L 102.89 75.31 L 101.63 74.80 L 101.05 74.46 L 66.24 51.60 L 65.38 51.11 L 64.33 50.69 L 63.28 50.43 L 61.81 50.33 L 60.68 50.45 L 59.64 50.72 L 58.29 51.33 L 57.36 51.97 L 56.56 52.70 L 55.66 53.87 L 55.01 55.19 L 54.62 56.61 L 54.53 58.08 L 54.72 59.54 L 55.19 60.94 L 55.73 61.93 L 56.65 63.09 L 57.19 63.59 L 57.98 64.19 L 84.72 81.74 L 85.44 82.28 L 86.59 83.29 L 89.26 85.97 L 91.76 88.72 L 92.38 89.52 L 94.07 92.11 L 95.23 94.72 L 96.20 97.78 L 96.85 100.88 L 97.31 104.43 L 97.36 106.10 L 97.36 133.99 L 97.48 135.38 L 97.75 136.43 L 98.18 137.47 L 98.74 138.40 L 99.45 139.27 L 99.99 139.78 L 100.86 140.43 L 101.85 140.96 L 102.87 141.32 L 104.32 141.58 L 105.80 141.54 L 107.24 141.22 L 108.58 140.63 L 109.79 139.78 L 110.81 138.72 L 111.60 137.47 L 112.13 136.10 L 112.35 134.99 L 112.41 133.99 L 112.41 106.36 Z";

function svgNode(documentNode, tagName, attributes) {
  const node = documentNode.createElementNS(SVG_NAMESPACE, tagName);
  for (const [name, value] of Object.entries(attributes)) {
    node.setAttribute(name, value);
  }
  return node;
}

export function steeringMarker(documentNode, className, { decorative = false } = {}) {
  const marker = el(documentNode, "span", `steering-symbol ${className}`);
  attachTooltip(documentNode, marker, STEERING_MARKER_TITLE);
  if (decorative) marker.setAttribute("aria-hidden", "true");
  else {
    marker.setAttribute("role", "img");
    marker.setAttribute("aria-label", STEERING_MARKER_TITLE);
  }
  const svg = svgNode(documentNode, "svg", {
    viewBox: "0 0 209.8 142", "aria-hidden": "true", focusable: "false",
  });
  svg.appendChild(svgNode(documentNode, "path", {
    d: STEERING_CONNECTOR_PATH, fill: "currentColor",
  }));
  for (const cx of ["38.30", "171.49"]) {
    svg.appendChild(svgNode(documentNode, "circle", {
      cx, cy: "38.34", r: "30.74", fill: "none",
      stroke: "currentColor", "stroke-width": "15.05",
    }));
  }
  marker.appendChild(svg);
  return marker;
}

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

// Active steering sessions first, ordinary sessions after — both groups keep
// their incoming relative order. Steering identity comes from the same
// current-holdings projection the card itself reads, never from a title,
// name, harness, or mode string, so a session only counts once its claim
// says so. Shared by Overview and Sessions so both screens agree on where a
// steering seat lands in the grid.
export function sortSessionsSteeringFirst(rows) {
  return (Array.isArray(rows) ? rows.slice() : []).sort((left, right) => (
    Number(steeringClaims(right).length > 0)
      - Number(steeringClaims(left).length > 0)
  ));
}

// Every project this session actively steers, from the same current-holdings
// projection the card and the sort above read — never a title, name, or mode
// string. A project-scoped session picker uses this alongside the session's
// own home project: a live steering claim is a membership fact on the
// project it targets, whether or not that is where the session started.
export function steeringProjectIds(row) {
  return steeringClaims(row).map((claim) => String(claimProjectId(claim)));
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
  const symbol = steeringMarker(
    documentNode, "session-steering-symbol", { decorative: true },
  );
  lead.appendChild(symbol);
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
