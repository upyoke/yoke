// Card renderers for the three live objects on the Overview frontier: items,
// sessions (rendered by the Sessions module), and deployment runs.

import { buildUniverseRoute } from "./universe_navigation.js";
import { itemDrillInHref } from "./universe_item_routes.js";
import { deliveryStageBar, workflowBadge } from "./universe_secondary_primitives.js";
import { relativeAge } from "./universe_time.js";
import { appendRunGates, runGateStatus } from "./universe_run_gates.js";
import { el, statePill } from "./universe_view_support.js";

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
    timestamp ? `${options.timeLabel || "updated"} ${relativeAge(timestamp)} ago` : null,
  ].filter(Boolean).join(" · ");
  if (meta) card.appendChild(el(
    documentNode, "span", "overview-item-card-meta", meta,
  ));
  return card;
}

function carriedItems(row) {
  if ((row.member_items || []).length) return row.member_items;
  return row.carried_work?.items || [];
}

function carriedReference(item) {
  return item.ref || item.public_ref || item.item_ref || `item ${item.item_id}`;
}

function runProjectId(context, row, scope) {
  const projects = typeof context.projects === "function" ? context.projects() : [];
  const project = projects.find((candidate) => (
    [candidate.id, candidate.slug, candidate.name].some(
      (value) => String(value) === String(row.project),
    )
  ));
  return project?.id || (scope !== "all" && scope.length === 1 ? scope[0] : null);
}

// A run card takes the whole view context rather than just its document:
// the gates it draws read their evidence through the client, so a card that
// only knew how to create elements could show that evidence existed and
// never let the approver open it.
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
  // The informational card is a link to the run; a gate's Approve and Reject
  // are buttons inside it. Nesting those in the anchor would be invalid, so
  // the link wraps what is readable and the gates sit beside it.
  const link = el(documentNode, "a", "overview-run-card-link");
  link.href = buildUniverseRoute(
    "deployments", scope === "all" ? null : scope.join(","),
  );
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
    documentNode, "strong", "overview-run-flow", row.flow || "flow unavailable",
  ));
  const details = el(documentNode, "details", "overview-run-details");
  details.appendChild(el(documentNode, "summary", null, "Details"));
  if ((row.stages || []).length) {
    details.appendChild(deliveryStageBar(documentNode, row.stages));
  }
  if (row.release_lineage) {
    const release = el(documentNode, "div", "overview-run-release");
    release.appendChild(el(documentNode, "span", null, "Release "));
    release.appendChild(el(
      documentNode, "code", null, String(row.release_lineage).slice(0, 12),
    ));
    details.appendChild(release);
  }

  const items = carriedItems(row);
  if (items.length) {
    const batch = el(documentNode, "div", "overview-run-batch");
    batch.appendChild(el(
      documentNode,
      "span",
      "overview-run-batch-title",
      `Carries · ${items.length} item${items.length === 1 ? "" : "s"}`,
    ));
    for (const item of items.slice(0, 6)) {
      const member = el(documentNode, "span", "overview-run-member");
      member.appendChild(el(
        documentNode, "code", null, carriedReference(item),
      ));
      member.appendChild(el(
        documentNode, "span", null, item.title || "",
      ));
      batch.appendChild(member);
    }
    if (items.length > 6) {
      batch.appendChild(el(
        documentNode,
        "span",
        "overview-run-member-more",
        `+${items.length - 6} more carried by this release`,
      ));
    }
    details.appendChild(batch);
  }

  const derivation = row.carried_work?.derivation;
  if (derivation) {
    details.appendChild(el(
      documentNode,
      "div",
      "overview-run-derived",
      [derivation.status, derivation.reason].filter(Boolean).join(" — "),
    ));
  }
  const timing = row.completed_at || row.started_at || row.created_at;
  const summary = [
    items.length
      ? `${items.length} ${items.length === 1 ? "item" : "items"}`
      : "environment run",
    row.release_lineage ? `release ${String(row.release_lineage).slice(0, 12)}` : null,
    timing ? `${status} ${relativeAge(timing)} ago` : status,
  ].filter(Boolean).join(" · ");
  link.appendChild(el(
    documentNode,
    "span",
    "overview-run-card-meta",
    summary,
  ));
  card.appendChild(link);
  appendRunGates(context, card, row.gates, options.onGateAction);
  if (details.children.length > 1) card.appendChild(details);
  const evidence = el(documentNode, "a", "overview-run-evidence", "QA evidence →");
  evidence.href = buildUniverseRoute(
    "qa-activity", runProjectId(context, row, scope), row.id || row.run_id,
  );
  card.appendChild(evidence);
  return card;
}
