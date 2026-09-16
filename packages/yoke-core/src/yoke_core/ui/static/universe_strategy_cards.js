// Strategy document cards: one card per document in the corpus, carrying the
// project it belongs to, its slug, how recently it was written, the summary
// its own `## Summary` heading declares, and the claim holding it.
//
// The claim box distinguishes the two kinds of hold rather than flattening
// them. A session hold is a steering seat, marked with the same symbol a
// steering session's own card uses and labelled STEERED — the label already
// says whose hold it is, so repeating "steering seat" beside it said the same
// word twice. An item hold is a Blitz: it names the item and its status,
// because which work is executing from this document is the fact a reader
// needs.

import { buildUniverseRoute } from "./universe_navigation.js";
import { steeringMarker } from "./universe_sessions_steering.js";
import { relativeAgePhrase } from "./universe_time.js";
import { el, statePill } from "./universe_view_support.js";

// Documents every project has from its cold start, in the order they build on
// each other rather than in the order they were last written: what this is
// for, where it is going, what it is going through, and how it gets there.
export const STANDING_DOC_ORDER = [
  "MISSION", "VISION", "LANDSCAPE", "MASTER-PLAN",
];

const STANDING_DOCS = new Set(STANDING_DOC_ORDER);
const DRAWN_STATES = new Set(["locked", "deferred", "reference"]);
const TERMINAL_ITEM_STATES = new Set(["done", "cancelled", "stopped"]);
const DAY_MS = 86_400_000;

export function isStandingDoc(doc) {
  return STANDING_DOCS.has(String(doc.slug || ""));
}

function staleTone(updatedAt, now = Date.now()) {
  const timestamp = new Date(updatedAt).getTime();
  if (Number.isNaN(timestamp)) return "unknown";
  const days = Math.max(0, now - timestamp) / DAY_MS;
  if (days < 1) return "today";
  if (days < 7) return "week";
  if (days < 30) return "month";
  return "old";
}

// The live hold on a document, or null. A Blitz whose item has finished is
// not a live hold: the claim row outlives the work, so reading it as current
// would show a completed item as still executing.
export function liveDocumentClaim(doc) {
  const kind = String(doc.execution_owner_kind || "");
  if (!kind) return null;
  if (
    kind === "item"
    && TERMINAL_ITEM_STATES.has(
      String(doc.execution_item_status || "").toLowerCase(),
    )
  ) return null;
  return { kind, doc };
}

function claimBox(documentNode, claim) {
  const steering = claim.kind === "session";
  const box = el(
    documentNode,
    "div",
    `strategy-doc-claim is-${steering ? "steering" : "blitz"}`,
  );
  if (steering) {
    box.appendChild(steeringMarker(
      documentNode, "strategy-doc-claim-symbol", { decorative: true },
    ));
  }
  box.appendChild(el(
    documentNode,
    "span",
    "strategy-doc-claim-label",
    steering ? "STEERED" : "Blitz",
  ));
  if (!steering) {
    box.appendChild(el(
      documentNode,
      "span",
      "strategy-doc-claim-holder",
      claim.doc.execution_item_ref || claim.doc.execution_item_title || "item",
    ));
    const pill = statePill(
      documentNode,
      claim.doc.execution_item_status,
      claim.doc.execution_item_status,
    );
    if (pill) box.appendChild(pill);
  }
  return box;
}

export function strategyDocumentCard(documentNode, doc, project) {
  const card = el(documentNode, "a", "strategy-doc-card");
  const projectId = String(doc.project_id || project.id);
  card.href = buildUniverseRoute("strategy", projectId, doc.slug);
  const head = el(documentNode, "div", "strategy-doc-card-head");
  head.appendChild(el(
    documentNode,
    "span",
    "strategy-doc-prefix",
    project.public_item_prefix || String(project.id),
  ));
  head.appendChild(el(
    documentNode, "span", "strategy-doc-slug", doc.slug || "Strategy",
  ));
  const state = String(doc.state || "").toLowerCase();
  if (DRAWN_STATES.has(state)) {
    head.appendChild(el(documentNode, "span", "strategy-doc-state", state));
  }
  const age = el(
    documentNode,
    "span",
    `strategy-doc-age is-${staleTone(doc.updated_at)}`,
  );
  age.appendChild(el(documentNode, "span", "strategy-doc-age-dot"));
  // The dot and the card's own subject already say this is when the document
  // was last written; the word "updated" in front of it was the third time.
  // Plain text rather than the pressable timestamp: a card is a glance, and
  // the exact moment belongs on the document the card opens.
  age.appendChild(el(
    documentNode, "span", null, relativeAgePhrase(doc.updated_at),
  ));
  head.appendChild(age);
  card.appendChild(head);
  const claim = liveDocumentClaim(doc);
  if (claim) card.appendChild(claimBox(documentNode, claim));
  card.appendChild(el(
    documentNode,
    "p",
    doc.summary ? "strategy-doc-summary" : "strategy-doc-summary is-missing",
    doc.summary || "No ## Summary heading",
  ));
  return card;
}

// Standing documents read in their own order; everything else reads
// most-recently-written first.
export function orderStrategyDocs(docs, standing) {
  const sorted = docs.slice();
  if (standing) {
    sorted.sort((left, right) => (
      STANDING_DOC_ORDER.indexOf(String(left.slug))
      - STANDING_DOC_ORDER.indexOf(String(right.slug))
    ));
    return sorted;
  }
  sorted.sort((left, right) => String(right.updated_at || "").localeCompare(
    String(left.updated_at || ""),
  ));
  return sorted;
}
