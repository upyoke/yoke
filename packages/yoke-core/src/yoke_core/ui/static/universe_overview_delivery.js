import {
  el, mergedRows, scopeBuckets, statePill,
} from "./universe_view_support.js";
import { holdScopedSection } from "./universe_held_reads.js";
import { ghostWhenInactive } from "./universe_views_overview_activation.js";
import { deliveryStageBar } from "./universe_secondary_primitives.js";
import { relativeTime } from "./universe_time.js";
import {
  appendCell,
  destinationHref,
  emptyTableRow,
  makeRowNavigable,
  overviewTable,
  projectDisplay,
  routeCell,
  SUMMARY_ROW_LIMIT,
} from "./universe_overview_primitives.js";

// What is shipping. The engine bounds run history and returns the newest
// receipts first, so the overview keeps that order before taking its summary.
export function loadDelivery(context, panel, getScope, activationFacts) {
  // Fan out per project so each project's own newest-N runs are held: a
  // universe-wide window would let a busy project crowd a quiet one out. Runs
  // always carry a project (the projects JOIN), so no null bucket is needed.
  const buckets = scopeBuckets("all", context.projects(), true);
  return holdScopedSection(
    context, panel, buckets,
    buckets.map((bucket) => ({
      functionId: "deployment_runs.list",
      payload: { project: bucket },
    })),
    getScope,
    (body, callResults, scope) => {
      const documentNode = body.ownerDocument;
      // Per-project holds are merged newest-first (roster grouping otherwise
      // interleaves projects) before the summary takes its slice.
      const rows = mergedRows(callResults, (result) => result.rows).sort(
        (left, right) => String(right.created_at || "").localeCompare(
          String(left.created_at || ""),
        ),
      );
      if (!rows.length) {
        ghostWhenInactive(context, activationFacts, "delivery", panel);
      }
      panel.setCount(`${rows.length} runs`);
      const table = overviewTable(
        documentNode,
        "overview-delivery-table",
        ["Run", "Project", "Target", "Stages", "Status", "When"],
      );
      const href = destinationHref("delivery", scope);
      for (const row of rows.slice(0, SUMMARY_ROW_LIMIT)) {
        const tableRow = el(documentNode, "tr", "overview-delivery-row");
        routeCell(
          documentNode,
          tableRow,
          row.id || row.run_id || "run",
          href,
          "overview-run-id",
        );
        appendCell(
          documentNode,
          tableRow,
          projectDisplay(context.projects(), row.project),
          "overview-project-cell",
        );
        appendCell(
          documentNode, tableRow,
          row.target_environment || row.target_tier || "—",
          "overview-target-cell",
        );
        const stages = (row.stages || []).length
          ? deliveryStageBar(documentNode, row.stages)
          : el(documentNode, "span", "secondary-muted", "—");
        appendCell(
          documentNode, tableRow, stages, "overview-delivery-stages",
        );
        const status = el(documentNode, "div", "overview-run-status");
        const statusPill = statePill(
          documentNode, row.status || "unknown", row.status || "unknown",
        );
        if (statusPill) status.appendChild(statusPill);
        if (row.waiting_on_approval) {
          status.appendChild(statePill(
            documentNode, "warning", "⏳ your approval",
          ));
        }
        appendCell(documentNode, tableRow, status);
        appendCell(
          documentNode,
          tableRow,
          relativeTime(documentNode, row.created_at),
          "overview-age-cell",
        );
        makeRowNavigable(
          documentNode, tableRow, href, row.id || row.run_id || "Delivery",
        );
        table.body.appendChild(tableRow);
      }
      if (!rows.length) {
        emptyTableRow(
          documentNode, table.body, 6, "No runs in this scope.",
        );
      }
      body.appendChild(table.wrap);
      renderLatestEnvironments(documentNode, body, rows);
    },
  );
}

// A concise answer to the question the run history alone makes surprisingly
// hard: what is the newest receipt for each environment? This mirrors the
// prototype's environment line and prevents an older red run from looking
// like the current state when a newer green run already superseded it.
function renderLatestEnvironments(documentNode, body, rows) {
  const latest = new Map();
  const sorted = [...rows].sort((left, right) =>
    String(right.created_at || "").localeCompare(String(left.created_at || "")),
  );
  for (const row of sorted) {
    const target = String(
      row.target_environment || row.target_tier || "",
    ).trim();
    if (!target) continue;
    const key = `${row.project || ""}:${target}`;
    if (!latest.has(key)) latest.set(key, row);
  }
  if (!latest.size) return;
  const line = el(documentNode, "div", "overview-environments");
  line.setAttribute("aria-label", "Latest by environment");
  for (const row of [...latest.values()].slice(0, 6)) {
    const fact = el(documentNode, "span", "overview-environment-fact");
    const label = [
      row.project,
      row.target_environment || row.target_tier,
    ].filter(Boolean).join(" · ");
    fact.appendChild(el(documentNode, "strong", null, label || "environment"));
    fact.appendChild(el(
      documentNode, "span", null, ` ${row.status || "unknown"} · `,
    ));
    fact.appendChild(relativeTime(documentNode, row.created_at));
    fact.setAttribute("data-status", String(row.status || "unknown"));
    line.appendChild(fact);
  }
  body.appendChild(line);
}
