// The Runs table on the Deployments page: one row per run, each a way into
// the run page, with what the run carries, where it stands, and the QA
// evidence its checks captured.

import { itemDrillInHref } from "./universe_item_routes.js";
import { el, statePill } from "./universe_view_support.js";
import { relativeTime } from "./universe_time.js";
import { renderStageStrip } from "./universe_stage_strip.js";
import { runGateStatus, runGates } from "./universe_run_gates.js";
import { evidenceStrip } from "./review_evidence_strip.js";
import { evidenceOf } from "./review_request_presentation.js";
import { runEvidence } from "./universe_run_evidence.js";
import {
  CARRIED_ITEMS_SHOWN,
  carriedItems,
  runDetailHref,
} from "./universe_overview_cards.js";
import {
  isTerminalizable,
  terminalizationDialog,
} from "./deployment_run_terminalization_dialog.js";

function memberLink(documentNode, member) {
  const href = itemDrillInHref({
    projectId: member.project_id,
    projectSequence: member.project_sequence,
    publicRef: member.ref || member.public_ref || member.item_ref,
  });
  const label = member.ref || member.public_ref || member.item_ref || `item ${member.item_id}`;
  const link = el(documentNode, href ? "a" : "span", "delivery-member", label);
  if (href) link.href = href;
  if (member.title) link.title = String(member.title);
  return link;
}

function carriesCell(documentNode, row) {
  const cell = el(documentNode, "td");
  const items = carriedItems(row);
  const members = el(documentNode, "div", "delivery-origin-items");
  if (!items.length) {
    members.appendChild(el(documentNode, "span", "secondary-muted", "environment run"));
  }
  for (const member of items.slice(0, CARRIED_ITEMS_SHOWN)) {
    members.appendChild(memberLink(documentNode, member));
  }
  if (items.length > CARRIED_ITEMS_SHOWN) {
    members.appendChild(el(
      documentNode, "span", "secondary-muted", `+${items.length - CARRIED_ITEMS_SHOWN} more`,
    ));
  }
  cell.appendChild(members);
  return cell;
}

function runProjectLabel(projects, projectSlug) {
  const normalized = String(projectSlug || "").toLowerCase();
  const project = projects.find((candidate) => (
    [candidate.id, candidate.slug, candidate.name].some(
      (value) => String(value || "").toLowerCase() === normalized,
    )
  ));
  const label = project?.slug || projectSlug || project?.name || "—";
  return project?.emoji ? `${project.emoji} ${label}` : label;
}

function runTimestamp(row) {
  return row.completed_at || row.started_at || row.created_at || null;
}

// The pictures behind this run: what its QA checks captured, or, for a run
// with none recorded yet, what its open request carries.
function evidenceCell(context, row, facts) {
  const cell = el(context.document, "td", "delivery-run-evidence-cell");
  let artifacts = runEvidence(facts, row.id).artifacts;
  if (!artifacts.length) {
    artifacts = runGates(row).flatMap((gate) => evidenceOf(gate).artifacts);
  }
  const strip = evidenceStrip(context, artifacts, { compact: true });
  if (strip) cell.appendChild(strip);
  else cell.appendChild(el(context.document, "span", "secondary-muted", "—"));
  // The row navigates to the run; a thumbnail opens its picture instead.
  cell.addEventListener("click", (event) => event.stopPropagation());
  return cell;
}

export const RUN_TABLE_COLUMNS = [
  "Release", "Project", "Carries", "Target", "Stages", "Status", "QA evidence", "When",
];

export function renderRunsTable(context, body, rows, options) {
  const documentNode = context.document;
  const { facts, flowLabels, scope, reload } = options;
  const projects = context.projects();
  if (!rows.length) {
    body.appendChild(el(documentNode, "p", "empty", "No runs in this scope."));
    return;
  }
  const wrap = el(documentNode, "div", "table-wrap");
  const table = el(documentNode, "table", "items delivery-runs-table");
  const head = el(documentNode, "tr");
  for (const label of RUN_TABLE_COLUMNS) head.appendChild(el(documentNode, "th", null, label));
  table.appendChild(head);
  for (const row of rows) {
    const href = runDetailHref(context, row, scope);
    const tr = el(documentNode, "tr", "delivery-run-row");
    tr.addEventListener("click", (event) => {
      if (event.target?.closest?.("a, button")) return;
      context.navigate(href);
    });
    const release = el(documentNode, "td");
    const title = el(documentNode, "a", "delivery-run-title", flowLabels.get(String(row.flow)) || row.flow || "flow unavailable");
    title.href = href;
    release.appendChild(title);
    release.appendChild(el(documentNode, "div", "mono delivery-run-id", row.id || "—"));
    tr.appendChild(release);
    tr.appendChild(el(documentNode, "td", null, runProjectLabel(projects, row.project)));
    tr.appendChild(carriesCell(documentNode, row));
    tr.appendChild(el(
      documentNode, "td", null, row.target_environment || row.target_tier || "—",
    ));
    const stages = el(documentNode, "td");
    stages.appendChild(renderStageStrip(documentNode, row.stages));
    tr.appendChild(stages);
    const status = el(documentNode, "td", "delivery-run-status");
    // A suspended run keeps whatever status it held when it stopped, so the
    // table reports the request instead — the same string the run card shows.
    const shown = runGateStatus(row) || row.status;
    const pill = statePill(documentNode, shown, shown);
    if (pill) status.appendChild(pill);
    if (isTerminalizable(row)) {
      const terminalize = el(
        documentNode, "button", "delivery-run-terminalize", "Terminalize",
      );
      terminalize.type = "button";
      terminalize.addEventListener("click", () => {
        body.appendChild(terminalizationDialog(context, row, reload));
      });
      status.appendChild(terminalize);
    }
    tr.appendChild(status);
    tr.appendChild(evidenceCell(context, row, facts));
    const when = el(documentNode, "td");
    when.appendChild(relativeTime(documentNode, runTimestamp(row)));
    tr.appendChild(when);
    table.appendChild(tr);
  }
  wrap.appendChild(table);
  body.appendChild(wrap);
}
