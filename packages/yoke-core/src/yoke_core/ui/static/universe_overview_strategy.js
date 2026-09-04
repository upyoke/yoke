// Strategy on the Overview is the live corpus itself: standing direction and
// executable plans, with authored summaries and current document claims.

import { buildUniverseRoute } from "./universe_navigation.js";
import { relativeAge } from "./universe_time.js";
import { el, settledScopedCalls, statePill } from "./universe_view_support.js";
import {
  callError,
  successfulResult,
} from "./universe_overview_primitives.js";

const STANDING_DOCS = new Set([
  "MISSION", "VISION", "LANDSCAPE", "MASTER-PLAN",
]);
const DRAWN_STATES = new Set(["locked", "deferred", "reference"]);
const TERMINAL_ITEM_STATES = new Set(["done", "cancelled", "stopped"]);
const DAY_MS = 86_400_000;

function staleTone(updatedAt, now = Date.now()) {
  const timestamp = new Date(updatedAt).getTime();
  if (Number.isNaN(timestamp)) return "unknown";
  const days = Math.max(0, now - timestamp) / DAY_MS;
  if (days < 1) return "today";
  if (days < 7) return "week";
  if (days < 30) return "month";
  return "old";
}

function claimForDocument(claims, doc) {
  const claim = claims.find((row) => (
    row.strategy_doc_slug === doc.slug
    && String(row.project_id) === String(doc.project_id)
  ));
  if (!claim) return null;
  if (
    claim.owner_kind === "item"
    && TERMINAL_ITEM_STATES.has(String(claim.item_status || "").toLowerCase())
  ) return null;
  return claim;
}

function claimBox(documentNode, claim) {
  const steering = claim.owner_kind === "session";
  const box = el(
    documentNode,
    "div",
    `overview-doc-claim is-${steering ? "steering" : "blitz"}`,
  );
  box.appendChild(el(
    documentNode,
    "span",
    "overview-doc-claim-label",
    steering ? "Steering" : "Blitz",
  ));
  box.appendChild(el(
    documentNode,
    "span",
    "overview-doc-claim-holder",
    steering ? "steering seat" : (claim.public_ref || claim.holder_label),
  ));
  if (!steering && claim.item_status) {
    const pill = statePill(
      documentNode, claim.item_status, claim.item_status,
    );
    if (pill) box.appendChild(pill);
  }
  return box;
}

function documentCard(documentNode, doc, claim, project) {
  const card = el(documentNode, "a", "overview-doc-card");
  const projectId = String(doc.project_id || project.id);
  card.href = buildUniverseRoute("strategy", projectId, doc.slug);
  const head = el(documentNode, "div", "overview-doc-card-head");
  head.appendChild(el(
    documentNode,
    "span",
    "overview-doc-prefix",
    project.public_item_prefix || String(project.id),
  ));
  head.appendChild(el(
    documentNode, "span", "overview-doc-slug", doc.slug || "Strategy",
  ));
  const state = String(doc.state || "").toLowerCase();
  if (DRAWN_STATES.has(state)) {
    head.appendChild(el(
      documentNode, "span", "overview-doc-state", state,
    ));
  }
  const age = el(
    documentNode,
    "span",
    `overview-doc-age is-${staleTone(doc.updated_at)}`,
  );
  age.appendChild(el(documentNode, "span", "overview-doc-age-dot"));
  age.appendChild(el(
    documentNode, "span", null, `updated ${relativeAge(doc.updated_at)} ago`,
  ));
  head.appendChild(age);
  card.appendChild(head);
  if (claim) card.appendChild(claimBox(documentNode, claim));
  card.appendChild(el(
    documentNode,
    "p",
    doc.summary
      ? "overview-doc-summary"
      : "overview-doc-summary is-missing",
    doc.summary || "No ## Summary heading",
  ));
  return card;
}

function selectedProjects(projects, scope) {
  if (scope === "all") return projects;
  const wanted = new Set((scope || []).map(String));
  return projects.filter((project) => wanted.has(String(project.id)));
}

export async function loadStrategy(context, bands, getScope) {
  const projects = context.projects();
  const callsFor = (functionId) => projects.map((project) => ({
    functionId,
    payload: {},
    target: { kind: "global", project_id: String(project.id) },
  }));
  const [docsRead, claimsRead] = await Promise.all([
    settledScopedCalls(context, callsFor("strategy.doc.list")),
    settledScopedCalls(context, callsFor("strategy.doc_claim.list")),
  ]);
  if (!context.isMounted()) return null;

  const paint = () => {
    const chosen = selectedProjects(projects, getScope());
    const documents = [];
    const claims = [];
    let failure = null;
    for (const project of chosen) {
      const index = projects.indexOf(project);
      const docResult = successfulResult(docsRead.callResults[index]);
      const claimResult = successfulResult(claimsRead.callResults[index]);
      if (!docResult || !claimResult) {
        failure = !docResult
          ? docsRead.callResults[index] : claimsRead.callResults[index];
        break;
      }
      for (const doc of docResult.docs || []) {
        if (doc.archived) continue;
        documents.push({ ...doc, project_id: project.id, project });
      }
      claims.push(...(claimResult.claims || []));
    }
    if (failure) {
      const message = callError(failure, "Strategy could not be loaded.");
      bands.standing.renderError(message);
      bands.plans.renderError(message);
      return;
    }
    const render = (band, docs) => {
      const cards = docs
        .sort((left, right) => String(right.updated_at || "").localeCompare(
          String(left.updated_at || ""),
        ))
        .map((doc) => documentCard(
          context.document,
          doc,
          claimForDocument(claims, doc),
          doc.project,
        ));
      band.setCount(cards.length);
      band.renderCards(cards, "No strategy documents in this band.", "overview-doc-grid");
    };
    render(
      bands.standing,
      documents.filter((doc) => STANDING_DOCS.has(doc.slug)),
    );
    render(
      bands.plans,
      documents.filter((doc) => !STANDING_DOCS.has(doc.slug)),
    );
  };
  paint();
  return paint;
}
