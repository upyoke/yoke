import {
  el,
  loadScopedSection,
  mergedRows,
  scopeBuckets,
  statePill,
} from "./universe_view_support.js";
import { ghostWhenInactive } from "./universe_views_overview_activation.js";
import { stageProgress } from "./universe_secondary_primitives.js";
import {
  ageTone,
  appendCell,
  destinationHref,
  emptyTableRow,
  makeRowNavigable,
  overviewTable,
  projectDisplay,
  SUMMARY_ROW_LIMIT,
} from "./universe_overview_primitives.js";

// What can run now and why, plus how much is blocked. One read serves the two
// table regions and the age/workflow footer.
export function loadFrontier(context, panel, scope, activationFacts) {
  const buckets = scopeBuckets(scope, context.projects(), false);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "frontier.list",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      const documentNode = body.ownerDocument;
      const ready = mergedRows(callResults, (result) => result.ready_rows);
      const blocked = mergedRows(callResults, (result) => result.blocked_rows);
      if (!ready.length && !blocked.length) {
        ghostWhenInactive(context, activationFacts, "frontier", panel);
      }
      const blockedItems = new Set(blocked.map((row) => row.item_id));
      panel.setCount(`${ready.length} runnable · ${blockedItems.size} blocked`);
      const href = destinationHref("frontier", scope);
      const table = overviewTable(
        documentNode,
        "overview-frontier-table",
        ["#", "Item", "Project", "Progress", "Why it can run", "Run in your harness"],
      );
      for (const row of ready.slice(0, SUMMARY_ROW_LIMIT)) {
        const tableRow = el(documentNode, "tr", "overview-ready-row");
        appendCell(
          documentNode,
          tableRow,
          el(
            documentNode,
            "span",
            "overview-rank",
            typeof row.rank === "number" ? String(row.rank + 1) : "—",
          ),
          "overview-rank-cell",
        );
        const item = el(documentNode, "div", "overview-item");
        const title = el(
          documentNode,
          "a",
          "overview-row-link overview-item-title",
          row.title || row.item_id || "Item",
        );
        title.href = href;
        item.appendChild(title);
        item.appendChild(el(
          documentNode, "span", "overview-item-ref", row.item_id || "—",
        ));
        appendCell(documentNode, tableRow, item, "overview-item-cell");
        appendCell(
          documentNode,
          tableRow,
          projectDisplay(context.projects(), row.project),
          "overview-project-cell",
        );
        appendCell(
          documentNode,
          tableRow,
          stageProgress(
            documentNode,
            row.stage_index,
            row.stage_count,
            row.stage_label || row.next_step,
          ),
          "overview-progress-cell",
        );
        appendCell(
          documentNode,
          tableRow,
          row.why_ready || "readiness reason unavailable",
          "overview-why-cell",
        );
        const command = el(
          documentNode, "code", "overview-command", row.run_command || "—",
        );
        command.title = "Run this text in your harness";
        appendCell(
          documentNode, tableRow, command, "overview-command-cell",
        );
        makeRowNavigable(documentNode, tableRow, href, row.item_id || "Frontier");
        table.body.appendChild(tableRow);
      }
      if (!ready.length) {
        emptyTableRow(
          documentNode, table.body, 6, "No ready work in this scope.",
        );
      }
      body.appendChild(table.wrap);

      const blockedHead = el(documentNode, "div", "overview-subhead");
      const blockedTitle = el(documentNode, "strong", null, "Blocked");
      blockedTitle.appendChild(el(
        documentNode,
        "span",
        "overview-subhead-count",
        ` · ${blockedItems.size}`,
      ));
      blockedHead.appendChild(blockedTitle);
      blockedHead.appendChild(el(
        documentNode,
        "span",
        "overview-subhead-detail",
        "why these cannot run yet",
      ));
      body.appendChild(blockedHead);
      if (!blocked.length) {
        body.appendChild(el(
          documentNode, "p", "overview-region-empty", "Nothing blocked in this scope.",
        ));
      }
      for (const row of blocked.slice(0, SUMMARY_ROW_LIMIT)) {
        const blockedRow = el(documentNode, "div", "overview-blocked-row");
        blockedRow.appendChild(el(
          documentNode, "span", "overview-blocked-icon", "⛔",
        ));
        const content = el(documentNode, "div", "overview-blocked-content");
        const primary = el(documentNode, "div", "overview-blocked-primary");
        const itemLink = el(
          documentNode, "a", "overview-row-link", row.item_id || "Item",
        );
        itemLink.href = href;
        primary.appendChild(itemLink);
        primary.appendChild(el(
          documentNode, "span", null, row.title || "",
        ));
        const gate = statePill(
          documentNode,
          row.gate_point || "blocked",
          row.gate_point || "blocked",
        );
        if (gate) primary.appendChild(gate);
        content.appendChild(primary);
        content.appendChild(el(
          documentNode,
          "div",
          "overview-blocked-reason",
          row.why || "blocking reason unavailable",
        ));
        blockedRow.appendChild(content);
        blockedRow.appendChild(el(
          documentNode,
          "span",
          "overview-blocked-on",
          row.blocking_item ? `on ${row.blocking_item}` : "blocking item unavailable",
        ));
        body.appendChild(blockedRow);
      }

      const uniqueItems = [];
      const seenItems = new Set();
      for (const row of [...ready, ...blocked]) {
        const key = String(row.item_id || "");
        if (key && seenItems.has(key)) continue;
        if (key) seenItems.add(key);
        uniqueItems.push(row);
      }
      const ageStrip = el(documentNode, "div", "overview-age-strip");
      ageStrip.appendChild(el(documentNode, "span", null, "🕐"));
      const cells = el(documentNode, "span", "overview-age-cells");
      for (const row of uniqueItems.slice(0, 20)) {
        const cell = el(documentNode, "i");
        const tone = ageTone(row.created_at);
        cell.setAttribute("data-age", tone);
        cell.title = `${row.item_id || "item"} · ${tone}`;
        cells.appendChild(cell);
      }
      ageStrip.appendChild(cells);
      ageStrip.appendChild(el(
        documentNode,
        "span",
        "overview-age-legend",
        "age: 🟢<6h · 🟡<1d · 🟠<3d · 🔴<1w · ⚪ older",
      ));
      const workflowCounts = new Map();
      for (const row of uniqueItems) {
        const workflow = String(row.workflow_id || "").trim();
        if (!workflow) continue;
        workflowCounts.set(workflow, (workflowCounts.get(workflow) || 0) + 1);
      }
      ageStrip.appendChild(el(
        documentNode,
        "span",
        "overview-workflow-counts",
        [...workflowCounts.entries()]
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([workflow, count]) => `${workflow} ${count}`)
          .join(" · ") || "workflow totals unavailable",
      ));
      body.appendChild(ageStrip);
    },
  );
}
