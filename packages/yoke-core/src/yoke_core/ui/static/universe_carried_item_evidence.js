// What a release's carried items proved on their own, and the reviews those
// items still owe a person, shown inside each item's own entry in a
// deployment card's Carries box.
//
// A deployment run's own checks record the run they ran in. An item's checks
// do not have to: an item-attached requirement records no deployment run at
// all, so grouping QA activity by run drops it and the release carrying that
// item shows nothing for it. This reads evidence for the items a card is
// actually about, keyed by the item, and keeps each row's own association, so
// a picture that proves nothing about this run is never presented as if it
// did.

import { evidenceStrip } from "./review_evidence_strip.js";
import { reviewRequestCard } from "./review_request_card.js";
import { loadPendingReviews } from "./universe_run_evidence.js";
import { el, settledScopedCalls } from "./universe_view_support.js";

// The most rows one read returns, and how many subjects share it: together
// they leave every subject in a call room for many more checks than an item
// accumulates, so what comes back is the subjects' whole QA rather than the
// most recent slice of it. A view showing more items than one call holds
// asks again rather than dropping the rest, because a silently truncated
// subject list reads as an item with no evidence at all.
const ITEM_ACTIVITY_LIMIT = 500;
const SUBJECTS_PER_CALL = 50;

// An item entry is a line in a card, not a gallery.
const CARRIED_EVIDENCE_SHOWN = 3;

export const EMPTY_CARRIED_ITEM_FACTS = Object.freeze({
  byItem: new Map(),
  pendingByRequirement: new Map(),
  failed: null,
});

// Membership names its item `id`; derived carried work names it `item_id`.
// Both are the same integer, and it is what evidence joins on.
export function carriedItemId(item) {
  const id = Number(item?.item_id ?? item?.id);
  return Number.isFinite(id) && id > 0 ? id : null;
}

function subjectsByProject(items) {
  const byProject = new Map();
  for (const item of items || []) {
    const id = carriedItemId(item);
    // A member whose project the reader cannot name is left out rather than
    // guessed into somebody else's project: the read is project-scoped.
    if (id === null || item.project_id == null) continue;
    const bucket = byProject.get(String(item.project_id)) || new Set();
    bucket.add(id);
    byProject.set(String(item.project_id), bucket);
  }
  return byProject;
}

// The QA and pending reviews for exactly the carried items on screen, read
// once for every card in the view. Scoping the read to those subjects is
// what keeps an item's evidence visible when a busy project has pushed it
// past the recent-activity window.
export async function loadCarriedItemEvidence(context, items) {
  const buckets = [...subjectsByProject(items).entries()];
  if (!buckets.length) return EMPTY_CARRIED_ITEM_FACTS;
  const calls = [];
  for (const [project, ids] of buckets) {
    const subjects = [...ids];
    for (let at = 0; at < subjects.length; at += SUBJECTS_PER_CALL) {
      calls.push({
        functionId: "qa.activity.list",
        payload: {
          project,
          item_ids: subjects.slice(at, at + SUBJECTS_PER_CALL),
          limit: ITEM_ACTIVITY_LIMIT,
        },
      });
    }
  }
  const [{ callResults, failed }, pendingByRequirement] = await Promise.all([
    settledScopedCalls(context, calls),
    loadPendingReviews(context, buckets.map(([project]) => Number(project))),
  ]);
  const byItem = new Map();
  for (const callResult of callResults) {
    const result = callResult.status === 200 && callResult.envelope?.success
      ? callResult.envelope.result || {}
      : null;
    for (const row of result?.rows || []) {
      const id = row.item_id ?? row.deployment_member_item_id;
      if (id == null) continue;
      const rows = byItem.get(String(id)) || [];
      rows.push(row);
      byItem.set(String(id), rows);
    }
  }
  return {
    byItem,
    pendingByRequirement,
    failed: failed
      ? failed.envelope?.error?.message
        || "Item QA evidence could not be loaded."
      : null,
  };
}

// What this card may honestly show beside this item: the checks recorded
// against this very run, plus the item's own checks that record no run at
// all — which are labelled rather than counted as proof of the run. A check
// recorded against a different run belongs to that run and stays there.
export function carriedItemEvidence(facts, itemId, runId) {
  const rows = facts?.byItem?.get(String(itemId)) || [];
  const wanted = String(runId || "");
  const checks = [];
  let unlinked = 0;
  for (const row of rows) {
    const recorded = String(row.deployment_run_id || "");
    if (recorded && recorded !== wanted) continue;
    if (!recorded) unlinked += 1;
    checks.push(row);
  }
  const seen = new Set();
  const artifacts = [];
  for (const check of checks) {
    for (const artifact of check.artifacts || []) {
      const key = String(artifact.id ?? artifact.artifact_id ?? "");
      if (key && seen.has(key)) continue;
      if (key) seen.add(key);
      artifacts.push({ ...artifact, requirement_id: check.requirement_id });
    }
  }
  return { checks, artifacts, unlinked };
}

// The reviews still waiting on this reader for these very checks. Keying off
// the checks already selected above is what keeps another item's — or
// another run's — request from being offered here.
export function carriedItemReviews(facts, checks) {
  const requests = new Map();
  for (const check of checks) {
    const request = facts?.pendingByRequirement?.get(String(check.requirement_id));
    if (request) requests.set(String(request.id), request);
  }
  return [...requests.values()];
}

function captionOf(checks) {
  const counts = new Map();
  // Where a check records the stage it ran at, the caption keeps it: that is
  // the rest of what ties this evidence to this release rather than to the
  // item at large.
  const stages = new Set();
  for (const check of checks) {
    const outcome = String(check.outcome || "unknown");
    counts.set(outcome, Number(counts.get(outcome) || 0) + 1);
    if (check.deployment_stage) stages.add(String(check.deployment_stage));
  }
  return [
    `QA · ${checks.length} check${checks.length === 1 ? "" : "s"}`,
    ...[...counts.entries()].map(([outcome, count]) => `${count} ${outcome}`),
    ...[...stages],
  ].join(" · ");
}

function unlinkedNote(unlinked, total) {
  const subject = unlinked === total
    ? `${unlinked === 1 ? "This check" : "These checks"} record`
    : `${unlinked} of these checks record`;
  return `${subject} no deployment run — item evidence, not proof of this run.`;
}

// `options.onDecide(request, action, node, note)` answers a review through
// the same resolver the Inbox uses, so the answer is the same act wherever
// it is given.
export function appendCarriedItemEvidence(context, host, options = {}) {
  const { item, runId, facts, onDecide } = options;
  const itemId = carriedItemId(item);
  if (itemId === null) return null;
  const { checks, artifacts, unlinked } = carriedItemEvidence(facts, itemId, runId);
  const reviews = carriedItemReviews(facts, checks);
  if (!checks.length && !reviews.length) return null;
  const documentNode = context.document;
  const wrap = el(documentNode, "div", "carried-item-evidence");
  wrap.appendChild(el(
    documentNode, "span", "carried-item-evidence-caption", captionOf(checks),
  ));
  const strip = evidenceStrip(context, artifacts, {
    compact: true,
    limit: CARRIED_EVIDENCE_SHOWN,
  });
  if (strip) wrap.appendChild(strip);
  if (unlinked) {
    wrap.appendChild(el(
      documentNode,
      "span",
      "carried-item-evidence-note",
      unlinkedNote(unlinked, checks.length),
    ));
  }
  for (const request of reviews) {
    wrap.appendChild(reviewRequestCard(context, request, {
      inline: true,
      // The strip above is this request's evidence; drawing it twice in one
      // item entry would say the item captured it twice.
      evidence: false,
      onAct: onDecide
        ? (row, action, node, note) => onDecide(request, action, node, note)
        : null,
    }));
  }
  host.appendChild(wrap);
  return wrap;
}

export const universeCarriedItemEvidence = {
  EMPTY_CARRIED_ITEM_FACTS,
  appendCarriedItemEvidence,
  carriedItemEvidence,
  carriedItemId,
  carriedItemReviews,
  loadCarriedItemEvidence,
};
