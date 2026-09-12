// Card renderers for the three live objects on the Overview frontier: items,
// sessions (rendered by the Sessions module), and deployment runs.

import { buildUniverseRoute } from "./universe_navigation.js";
import { itemDrillInHref } from "./universe_item_routes.js";
import { deliveryStageBar, workflowBadge } from "./universe_secondary_primitives.js";
import { relativeAgePhrase } from "./universe_time.js";
import { appendRunGates, runGateStatus, runGates } from "./universe_run_gates.js";
import { evidenceStrip } from "./review_evidence_strip.js";
import { runEvidence, runFlowName } from "./universe_run_evidence.js";
import { el, statePill } from "./universe_view_support.js";

// How many carried items a card lists before it says "+N more".
export const CARRIED_ITEMS_SHOWN = 3;

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

export function overviewItemCard(documentNode, row, scope, options = {}) {
  const reference = itemReference(row);
  const card = el(
    documentNode,
    "a",
    `overview-item-card${options.tone ? ` is-${options.tone}` : ""}`,
  );
  card.href = itemHref(row, scope);
  const top = el(documentNode, "div", "overview-item-card-head");
  top.appendChild(el(documentNode, "span", "overview-item-card-ref", reference));
  top.appendChild(workflowBadge(documentNode, row.workflow_id || "item"));
  const status = statePill(
    documentNode,
    row.status || row.stage_label,
    row.stage_label || row.status,
  );
  if (status) top.appendChild(status);
  card.appendChild(top);
  card.appendChild(el(
    documentNode,
    "strong",
    "overview-item-card-title",
    row.title || reference,
  ));

  if (options.flag) {
    const flag = el(
      documentNode,
      "div",
      `overview-item-flag is-${options.flag.tone || "neutral"}`,
    );
    flag.appendChild(el(
      documentNode, "span", "overview-item-flag-label", options.flag.label,
    ));
    flag.appendChild(el(
      documentNode, "span", "overview-item-flag-copy", options.flag.text,
    ));
    card.appendChild(flag);
  }

  const timestamp = options.timestamp || row.updated_at || row.created_at;
  const meta = [
    options.meta,
    timestamp ? `${options.timeLabel || "updated"} ${relativeAgePhrase(timestamp)}` : null,
  ].filter(Boolean).join(" · ");
  if (meta) card.appendChild(el(
    documentNode, "span", "overview-item-card-meta", meta,
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
  const projectId = runProjectId(context, row, scope);
  return buildUniverseRoute(
    "deployments", projectId == null ? null : String(projectId), row.id || row.run_id,
  );
}

// What the run carries, listed on the card: the first few items, and an
// honest "+N more" for the rest. Membership is who the pipeline moves to
// done; for an environment run that owns nothing the derived contents stand
// in, and a run that carries nothing says so in its meta line instead.
export function appendCarried(documentNode, host, row) {
  const items = carriedItems(row);
  if (!items.length) return null;
  const batch = el(documentNode, "div", "overview-run-batch");
  batch.appendChild(el(
    documentNode,
    "span",
    "overview-run-batch-title",
    `Carries · ${items.length} item${items.length === 1 ? "" : "s"}`,
  ));
  for (const item of items.slice(0, CARRIED_ITEMS_SHOWN)) {
    const member = el(documentNode, "span", "overview-run-member");
    member.appendChild(el(documentNode, "code", null, carriedReference(item)));
    member.appendChild(el(documentNode, "span", null, item.title || ""));
    batch.appendChild(member);
  }
  if (items.length > CARRIED_ITEMS_SHOWN) {
    batch.appendChild(el(
      documentNode,
      "span",
      "overview-run-member-more",
      `+${items.length - CARRIED_ITEMS_SHOWN} more carried by this release`,
    ));
  }
  host.appendChild(batch);
  return batch;
}

// A run card takes the whole view context rather than just its document:
// the request it folds in reads its evidence through the client, so a card
// that only knew how to create elements could show that evidence existed
// and never let the approver open it. `options.facts` carries the flow
// names and QA checks read once for the whole band.
export function overviewRunCard(context, row, scope, options = {}) {
  const documentNode = context.document;
  // A run stopped at a gate is not executing and not failed. Its own status
  // still says whichever it was when the pipeline suspended, so the gate is
  // what the card reports: one string drives the edge and the pill together.
  const status = runGateStatus(row) || String(row.status || "unknown");
  const card = el(
    documentNode,
    "div",
    `overview-run-card is-${status.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`,
  );
  // The informational card is a link to the run; a request's Approve and
  // Reject are buttons inside it. Nesting those in the anchor would be
  // invalid, so the link wraps what is readable and the request sits beside.
  const link = el(documentNode, "a", "overview-run-card-link");
  link.href = runDetailHref(context, row, scope);
  const head = el(documentNode, "div", "overview-run-card-head");
  head.appendChild(el(
    documentNode, "span", "overview-run-id", row.id || row.run_id || "run",
  ));
  head.appendChild(el(
    documentNode,
    "span",
    "overview-run-environment",
    row.target_environment || row.target_tier || "environment unavailable",
  ));
  const statusNode = statePill(documentNode, status, status);
  if (statusNode) head.appendChild(statusNode);
  link.appendChild(head);
  link.appendChild(el(
    documentNode, "strong", "overview-run-flow", runFlowName(options.facts, row),
  ));
  if ((row.stages || []).length) {
    link.appendChild(deliveryStageBar(documentNode, row.stages));
  }
  const items = carriedItems(row);
  const timing = row.completed_at || row.started_at || row.created_at;
  link.appendChild(el(documentNode, "span", "overview-run-card-meta", [
    items.length
      ? `${items.length} ${items.length === 1 ? "item" : "items"}`
      : "environment run",
    row.release_lineage ? `release ${String(row.release_lineage).slice(0, 12)}` : null,
    timing ? `${status} ${relativeAgePhrase(timing)}` : status,
  ].filter(Boolean).join(" · ")));
  card.appendChild(link);
  appendCarried(documentNode, card, row);
  const derivation = row.carried_work?.derivation;
  if (derivation && !items.length) {
    card.appendChild(el(
      documentNode,
      "div",
      "overview-run-derived",
      [derivation.status, derivation.reason].filter(Boolean).join(" — "),
    ));
  }
  appendRunGates(context, card, row.gates, options.onGateAction);
  // The request folded in above already shows the evidence it rests on; a
  // run with no open request shows what its QA checks captured instead.
  if (!runGates(row).length) {
    const artifacts = runEvidence(options.facts, row.id || row.run_id).artifacts;
    const strip = evidenceStrip(context, artifacts, { compact: true });
    if (strip) {
      const wrap = el(documentNode, "div", "overview-run-evidence");
      wrap.appendChild(el(documentNode, "span", "overview-run-batch-title", "QA evidence"));
      wrap.appendChild(strip);
      card.appendChild(wrap);
    }
  }
  return card;
}
