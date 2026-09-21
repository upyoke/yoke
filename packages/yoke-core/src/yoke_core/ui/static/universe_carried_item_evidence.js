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

import { normalizedArtifacts } from "./review_evidence_strip.js";
import { reviewRequestCard } from "./review_request_card.js";
import { evidenceOf } from "./review_request_presentation.js";
import { classifyMemberQa } from "./qa_state.js";
import { paintMemberHistory } from "./qa_member_history.js";
import { loadPendingReviews } from "./universe_run_evidence.js";
import { appendRunConclusion } from "./qa_run_conclusion.js";
import { el, settledScopedCalls } from "./universe_view_support.js";

// How many checks one item may contribute, and how many items share a call.
// The read bounds `limit` PER ITEM for an `item_ids` request, so a busy
// subject cannot spend another subject's share and leave it looking like an
// item with no evidence and no waiting review. An item that has more than
// this comes back cut short and named, which the entry then says out loud.
// A view showing more items than one call holds asks again rather than
// dropping the rest, for the same reason.
const CHECKS_PER_ITEM = 20;
const SUBJECTS_PER_CALL = 50;

export const EMPTY_CARRIED_ITEM_FACTS = Object.freeze({
  byItem: new Map(),
  pendingByRequirement: new Map(),
  pendingByItem: new Map(),
  truncatedGroups: new Set(),
  perGroupLimit: CHECKS_PER_ITEM,
  failed: null,
});

// One item's checks within one deployment run — the unit the read bounds,
// so the unit a caller can honestly report as cut short.
function groupKey(itemId, runId) {
  return `${itemId}|${runId || ""}`;
}

// Membership names its item `id`; derived carried work names it `item_id`.
// Both are the same integer, and it is what evidence joins on.
export function carriedItemId(item) {
  const id = Number(item?.item_id ?? item?.id);
  return Number.isFinite(id) && id > 0 ? id : null;
}

// Each subject is an item drawn under one run, so the read can be sized by
// what is on screen rather than by every release the item has ever been in.
function subjectsByProject(items) {
  const byProject = new Map();
  for (const item of items || []) {
    const id = carriedItemId(item);
    // A member whose project the reader cannot name is left out rather than
    // guessed into somebody else's project: the read is project-scoped.
    if (id === null || item.project_id == null) continue;
    const key = String(item.project_id);
    const bucket = byProject.get(key) || { items: new Set() };
    bucket.items.add(id);
    byProject.set(key, bucket);
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
  for (const [project, bucket] of buckets) {
    const subjects = [...bucket.items];
    for (let at = 0; at < subjects.length; at += SUBJECTS_PER_CALL) {
      calls.push({
        functionId: "qa.activity.list",
        payload: {
          project,
          item_ids: subjects.slice(at, at + SUBJECTS_PER_CALL),
          // History across releases is what the card summarises. The
          // per-item bound still trims old checks inside one run group.
          limit: CHECKS_PER_ITEM,
        },
      });
    }
  }
  const [{ callResults, failed }, pendingByRequirement] = await Promise.all([
    settledScopedCalls(context, calls),
    loadPendingReviews(context, buckets.map(([project]) => Number(project))),
  ]);
  const byItem = new Map();
  const truncatedGroups = new Set();
  for (const callResult of callResults) {
    const result = callResult.status === 200 && callResult.envelope?.success
      ? callResult.envelope.result || {}
      : null;
    for (const row of result?.rows || []) {
      // The same rule the read partitions on, so what it bounded per item
      // and what this groups per item are the same set.
      const id = row.item_id ?? row.deployment_member_item_id;
      if (id == null) continue;
      const rows = byItem.get(String(id)) || [];
      rows.push(row);
      byItem.set(String(id), rows);
    }
    for (const group of result?.item_selection?.truncated_groups || []) {
      truncatedGroups.add(groupKey(group.item_id, group.deployment_run_id));
    }
  }
  return {
    byItem,
    pendingByRequirement,
    pendingByItem: reviewsByItem(pendingByRequirement),
    truncatedGroups,
    perGroupLimit: CHECKS_PER_ITEM,
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

// A waiting review names the item it is about, so the reviews for an item
// are known without consulting its checks at all. That independence is the
// point: bounding an item's history is a choice about old thumbnails, and it
// must never be allowed to take a live request off the page with them.
function reviewsByItem(pendingByRequirement) {
  const byItem = new Map();
  for (const request of (pendingByRequirement || new Map()).values()) {
    const subject = request.subject_context?.subject || {};
    // A release's per-member review names its item in its own field: the
    // schema keeps `item_id` null for anything run scoped, so indexing only
    // that would drop exactly the reviews a release card is about.
    const itemId = subject.item_id ?? subject.deployment_member_item_id;
    if (itemId == null) continue;
    const requests = byItem.get(String(itemId)) || [];
    requests.push(request);
    byItem.set(String(itemId), requests);
  }
  return byItem;
}

// The reviews still waiting on this reader for this item in this run. The
// item's own reviews come from the request index, so a truncated history
// cannot hide one; the checks on screen add the reviews whose request names
// a run rather than an item, which is how a release's per-member check is
// addressed. Either way a request recorded against a different run belongs
// to that run and is not offered here.
export function carriedItemReviews(facts, itemId, runId, checks) {
  const requests = new Map();
  const wanted = String(runId || "");
  for (const request of facts?.pendingByItem?.get(String(itemId)) || []) {
    const recorded = String(request.subject_context?.subject?.deployment_run_id || "");
    if (recorded && recorded !== wanted) continue;
    requests.set(String(request.id), request);
  }
  for (const check of checks) {
    const request = facts?.pendingByRequirement?.get(String(check.requirement_id));
    if (request) requests.set(String(request.id), request);
  }
  return [...requests.values()];
}

// `options.onDecide(request, action, node, note)` answers a review through
// the same resolver the Inbox uses, so the answer is the same act wherever
// it is given.
export function appendCarriedItemEvidence(context, host, options = {}) {
  const { item, runId, facts, onDecide } = options;
  const itemId = carriedItemId(item);
  if (itemId === null) return null;
  const { checks } = carriedItemEvidence(facts, itemId, runId);
  const history = facts?.byItem?.get(String(itemId)) || checks;
  const reviews = carriedItemReviews(facts, itemId, runId, checks);
  const memberState = classifyMemberQa(history, { runId });
  // A member with no executable check is still a fact: waived, no-obligation,
  // and never-asked used to render as a bare title.
  const drawnRequests = new Set(reviews.map((request) => String(request.id)));
  const documentNode = context.document;
  const wrap = el(
    documentNode,
    "div",
    `carried-item-evidence is-${String(memberState.id).replaceAll("_", "-")}`,
  );
  const painted = paintMemberHistory(context, wrap, {
    itemId, runId, facts, history, memberState,
  });
  // A CI check that captured nothing still proved a tree. History lists
  // that row; this keeps the Actions run openable on the folded face.
  for (const check of checks) {
    if ((check.artifacts || []).length) continue;
    appendRunConclusion(
      documentNode, wrap, check, "carried-item-run-conclusion",
    );
  }
  // The strip above is this item's latest pictures, which is not the same
  // thing as this request's evidence: the reviewed capture may be older than
  // the latest few, or the strip may be empty. Its own evidence is suppressed
  // only where every artifact it rests on is demonstrably already on screen
  // — drawn, not merely passed in, since the strip folds everything past its
  // limit behind "+N more" where nobody has seen it yet.
  const shown = new Set(
    painted.shown.map((artifact) => String(artifact.id)),
  );
  for (const request of reviews) {
    const evidence = evidenceOf(request);
    const own = normalizedArtifacts(evidence.artifacts, {
      requirementId: evidence.requirementId,
    }).map((artifact) => String(artifact.id));
    const alreadyShown = own.length > 0 && own.every((id) => shown.has(id));
    wrap.appendChild(reviewRequestCard(context, request, {
      inline: true,
      evidence: !alreadyShown,
      onAct: onDecide
        ? (row, action, node, note) => onDecide(request, action, node, note)
        : null,
    }));
  }
  host.appendChild(wrap);
  // A caption is this member's QA state, not its pictures. The run-wide
  // strip stands down only when this wrap already showed tiles or a review
  // that would otherwise repeat there.
  return {
    node: wrap,
    requestIds: drawnRequests,
    drewEvidence: painted.drewEvidence || reviews.length > 0,
  };
}

export const universeCarriedItemEvidence = {
  EMPTY_CARRIED_ITEM_FACTS,
  appendCarriedItemEvidence,
  carriedItemEvidence,
  carriedItemId,
  carriedItemReviews,
  loadCarriedItemEvidence,
};
