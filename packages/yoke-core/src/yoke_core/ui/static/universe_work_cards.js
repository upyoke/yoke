// Card renderers for the three live objects on the Overview frontier: items,
// sessions (rendered by the Sessions module), and deployment runs.

import {
  buildUniverseRoute,
  deploymentRunHref,
} from "./universe_navigation.js";
import { itemDrillInHref } from "./universe_item_routes.js";
import { NO_ENVIRONMENT_LABEL } from "./deployment_environment_copy.js";
import { deliveryStageBar, workflowBadge } from "./universe_secondary_primitives.js";
import { relativeAgePhrase } from "./universe_time.js";
import { appendRunGates, runGateStatus, runGates } from "./universe_run_gates.js";
import { evidenceStrip } from "./review_evidence_strip.js";
import { appendCarriedItemEvidence } from "./universe_carried_item_evidence.js";
import { runEvidence, runFlowName } from "./universe_run_evidence.js";
import { itemClaimantControl } from "./universe_item_claimant.js";
import { navIcon } from "./universe_nav_sidebar.js";
import {
  appendMoreDisclosure,
} from "./universe_sessions_holdings_disclosure.js";
import { itemStatusDisclosure } from "./universe_item_status_pill.js";
import { renderStageStrip } from "./universe_stage_strip.js";
import { el, statePill } from "./universe_view_support.js";

// How many carried items a card lists before it says "+N more".
export const CARRIED_ITEMS_SHOWN = 3;

// A run in one of these states is over; nothing it waits on can still
// apply to it.
const TERMINAL_RUN_STATUSES = new Set(["succeeded", "failed", "cancelled"]);
const TERMINAL_ITEM_STATES = new Set(["done", "cancelled", "stopped"]);

function itemReference(row) {
  return String(row.public_ref || row.item_id || row.id || "Item");
}

function itemHref(row, scope) {
  return itemDrillInHref({
    projectId: row.project_id,
    projectSequence: row.project_sequence,
    publicRef: itemReference(row),
  }) || buildUniverseRoute("items", scope === "all" ? null : scope.join(","));
}

export function workItemCard(documentNode, row, scope, options = {}) {
  const reference = itemReference(row);
  // An article rather than one card-wide link: the card carries its own
  // controls — a status pill, a claiming session, a deployment — and an
  // interactive control inside an anchor is neither reachable by keyboard
  // nor clickable without also navigating. The ref and the title stay links,
  // which is what the whole-card anchor was ever for.
  const card = el(
    documentNode,
    "article",
    `work-item-card${options.tone ? ` is-${options.tone}` : ""}`,
  );
  const href = itemHref(row, scope);
  const top = el(documentNode, "div", "work-item-card-head");
  const ref = el(documentNode, "a", "work-item-card-ref", reference);
  ref.href = href;
  top.appendChild(ref);
  top.appendChild(workflowBadge(documentNode, row.workflow_id || "item"));
  const status = statePill(
    documentNode,
    row.status || row.stage_label,
    row.stage_label || row.status,
  );
  if (status) top.appendChild(status);
  // The age follows the status chip inline rather than owning a line of its
  // own or being pushed to the card's right edge: it qualifies the chip, and
  // the head already wraps, so a narrow card drops it to a second line
  // instead of truncating it.
  const timestamp = options.timestamp || row.updated_at || row.created_at;
  if (timestamp) {
    const when = el(
      documentNode,
      "time",
      "work-item-card-when",
      `${options.timeLabel || "updated"} ${relativeAgePhrase(timestamp)}`,
    );
    when.setAttribute("datetime", timestamp);
    top.appendChild(when);
  }
  card.appendChild(top);
  const title = el(documentNode, "strong", "work-item-card-title");
  const titleLink = el(
    documentNode, "a", "overview-card-link", row.title || reference,
  );
  titleLink.href = href;
  title.appendChild(titleLink);
  card.appendChild(title);

  // Progress belongs inside the card: a strip that spanned the grid row
  // stopped saying which item it described.
  if ((options.stages || []).length) {
    const progress = el(documentNode, "div", "work-item-card-progress");
    progress.appendChild(renderStageStrip(documentNode, options.stages));
    card.appendChild(progress);
  }

  if (
    options.flag
    && !TERMINAL_ITEM_STATES.has(String(row.status || "").toLowerCase())
  ) {
    card.appendChild(itemStatusDisclosure(documentNode, options.flag));
  }

  if (options.meta) card.appendChild(el(
    documentNode, "span", "work-item-card-meta", options.meta,
  ));
  return card;
}

export function carriedItems(row) {
  if ((row.member_items || []).length) return row.member_items;
  return row.carried_work?.items || [];
}

function carriedReference(item) {
  return item.ref || item.public_ref || item.item_ref || `item ${item.item_id}`;
}

export function runProjectId(context, row, scope) {
  const projects = typeof context.projects === "function" ? context.projects() : [];
  const project = projects.find((candidate) => (
    [candidate.id, candidate.slug, candidate.name].some(
      (value) => String(value) === String(row.project),
    )
  ));
  return project?.id || (scope !== "all" && scope.length === 1 ? scope[0] : null);
}

export function runDetailHref(context, row, scope) {
  return deploymentRunHref(runProjectId(context, row, scope), row.id || row.run_id);
}

// What the run carries, listed on the card: the first few items, and an
// honest "+N more" for the rest. Membership is who the pipeline moves to
// done; for an environment run that owns nothing the derived contents stand
// in, and a run that carries nothing says so in its meta line instead.
//
// Each entry also carries what that one item proved and what it still owes a
// reviewer, because that is the item's own fact rather than the release's:
// `options.facts` is the carried-item evidence read once for the whole band,
// and `options.onDecide` answers a review from here.
export function appendCarried(context, host, row, options = {}) {
  const documentNode = context.document;
  const items = carriedItems(row);
  // Which requests these member rows took responsibility for, so a caller
  // drawing the release's gates beside them does not draw one of them twice.
  const drawnRequests = new Set();
  // Whether any member drew evidence of its own. A caller that also has a
  // run-wide strip to fall back on needs to know, because run-wide evidence
  // carries no item: the same "step 2" tile under two different members
  // reads as one unattributed pair.
  let drewEvidence = false;
  if (!items.length) {
    return { node: null, requestIds: drawnRequests, drewEvidence };
  }
  const batch = el(documentNode, "div", "release-batch");
  batch.appendChild(el(
    documentNode,
    "span",
    "release-batch-title",
    `Carries · ${items.length} item${items.length === 1 ? "" : "s"}`,
  ));
  const memberFor = (item) => {
    const member = el(documentNode, "div", "release-member");
    member.appendChild(el(documentNode, "code", null, carriedReference(item)));
    member.appendChild(el(documentNode, "span", null, item.title || ""));
    const drawn = appendCarriedItemEvidence(context, member, {
      item,
      runId: row.id || row.run_id,
      facts: options.facts,
      onDecide: options.onDecide,
    });
    for (const id of drawn?.requestIds || []) drawnRequests.add(id);
    if (drawn) drewEvidence = true;
    return member;
  };
  for (const item of items.slice(0, CARRIED_ITEMS_SHOWN)) {
    batch.appendChild(memberFor(item));
  }
  // The rest are here rather than counted: "+6 more" named a number and
  // left the six unreachable from the card that named them.
  if (items.length > CARRIED_ITEMS_SHOWN) {
    const region = el(documentNode, "div", "release-member-rest");
    region.setAttribute("role", "region");
    region.setAttribute("aria-label", "More carried items");
    for (const item of items.slice(CARRIED_ITEMS_SHOWN)) {
      region.appendChild(memberFor(item));
    }
    batch.appendChild(region);
    appendMoreDisclosure(documentNode, batch, {
      key: `release-carried:${row.id || row.run_id}`,
      hiddenCount: items.length - CARRIED_ITEMS_SHOWN,
      region,
      label: "carried by this release",
      className: "release-member-more",
    });
  }
  host.appendChild(batch);
  return { node: batch, requestIds: drawnRequests, drewEvidence };
}

// A run card takes the whole view context rather than just its document:
// the request it folds in reads its evidence through the client, so a card
// that only knew how to create elements could show that evidence existed
// and never let the approver open it. `options.facts` carries the flow
// names and QA checks read once for the whole band, and `options.itemFacts`
// the same for what each carried item proved on its own.
export function shippingRunCard(context, row, scope, options = {}) {
  const documentNode = context.document;
  // A run stopped at a gate is not executing and not failed. Its own status
  // still says whichever it was when the pipeline suspended, so the gate is
  // what the card reports: one string drives the edge and the pill together.
  const status = runGateStatus(row) || String(row.status || "unknown");
  const card = el(
    documentNode,
    "div",
    `shipping-run-card is-${status.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`,
  );
  // The card is readable text, not one big control. Its run name is the
  // link to the run, each screenshot opens its own evidence, and a
  // request's Approve and Reject are buttons. A card-wide anchor used to
  // wrap everything readable, so hovering blank space lit the whole card,
  // the text under the cursor could not be selected, and a click meant for
  // a screenshot navigated to the run instead.
  const head = el(documentNode, "div", "shipping-run-card-head");
  const runLink = el(
    documentNode, "a", "shipping-run-id", row.id || row.run_id || "run",
  );
  runLink.href = runDetailHref(context, row, scope);
  head.appendChild(runLink);
  head.appendChild(el(
    documentNode,
    "span",
    "shipping-run-environment",
    row.target_environment || row.target_tier || NO_ENVIRONMENT_LABEL,
  ));
  const statusNode = statePill(documentNode, status, status);
  if (statusNode) head.appendChild(statusNode);
  card.appendChild(head);
  // Directly under the identity row, because "why has this not started" is
  // the first question a waiting run raises. The lock belongs to the
  // project, not to this run: the session holding it is serializing every
  // deploy in that project and may have started none of them.
  const lock = TERMINAL_RUN_STATUSES.has(status)
    ? null : options.deployLocks?.get(String(row.project || ""));
  // The lock reads as something the session holds, so it renders inside that
  // session's own chip rather than as a box the session sits in. Filed the
  // other way round it said the session belonged to the lock and the lock
  // belonged to this run, and neither is true.
  if (lock && options.renderFullSession) {
    const lockNote = el(documentNode, "span", "shipping-run-lock");
    const lockIcon = el(documentNode, "span", "shipping-run-lock-icon", "🔒");
    lockIcon.setAttribute("aria-hidden", "true");
    lockNote.appendChild(lockIcon);
    lockNote.appendChild(el(
      documentNode,
      "span",
      "shipping-run-lock-label",
      `holds deploy lock (${row.project}, project-wide)`,
    ));
    const lockRow = el(documentNode, "div", "shipping-run-lock-row");
    lockRow.appendChild(itemClaimantControl(documentNode, lock, {
      renderFullSession: options.renderFullSession,
      label: `Show the session holding the ${row.project} deploy lock`,
      note: lockNote,
    }));
    card.appendChild(lockRow);
  }
  card.appendChild(el(
    documentNode, "strong", "shipping-run-flow", runFlowName(options.facts, row),
  ));
  if ((row.stages || []).length) {
    card.appendChild(deliveryStageBar(documentNode, row.stages));
  }
  const items = carriedItems(row);
  const timing = row.completed_at || row.started_at || row.created_at;
  // The pill above already carries the status; repeating it here spent the
  // card's one meta line saying the same word twice.
  card.appendChild(el(documentNode, "span", "shipping-run-card-meta", [
    items.length
      ? `${items.length} ${items.length === 1 ? "item" : "items"}`
      : "environment run",
    row.release_lineage ? `release ${String(row.release_lineage).slice(0, 12)}` : null,
    timing ? relativeAgePhrase(timing) : null,
  ].filter(Boolean).join(" · ")));
  const carried = appendCarried(context, card, row, {
    facts: options.itemFacts,
    onDecide: options.onItemDecision,
  });
  const derivation = row.carried_work?.derivation;
  if (derivation && !items.length) {
    card.appendChild(el(
      documentNode,
      "div",
      "shipping-run-derived",
      [derivation.status, derivation.reason].filter(Boolean).join(" — "),
    ));
  }
  appendRunGates(context, card, row.gates, options.onGateAction, {
    drawnRequestIds: carried.requestIds,
  });
  // The request folded in above already shows the evidence it rests on, and
  // so does each carried member that drew its own. This run-wide strip is
  // the last resort for a run whose evidence nothing else has shown — an
  // environment run carrying no items, or members whose checks it does not
  // hold. Drawn beside per-member evidence it repeated the same tiles with
  // their item stripped off, so one release showed "step 2" and "step 5"
  // twice with nothing saying whose they were.
  if (!runGates(row).length && !carried.drewEvidence) {
    const artifacts = runEvidence(options.facts, row.id || row.run_id).artifacts;
    const strip = evidenceStrip(
      context, artifacts, { compact: true, stepCaptionsOnly: true },
    );
    if (strip) {
      const wrap = el(documentNode, "div", "shipping-run-evidence");
      wrap.appendChild(el(documentNode, "span", "release-batch-title", "QA evidence"));
      wrap.appendChild(strip);
      card.appendChild(wrap);
    }
  }
  return card;
}
