import { buildUniverseRoute } from "./universe_navigation.js";
import {
  el,
  loadScopedPanels,
  mergedRows,
  scopeBuckets,
  section,
  settledScopedCalls,
  statePill,
} from "./universe_view_support.js";
import {
  metricStrip,
  stageProgress,
  workflowBadge,
} from "./universe_secondary_primitives.js";

const LIVE_SESSION_STATES = ["active", "stale"];

function appendPanelDetail(documentNode, panel, text) {
  panel.children[0].appendChild(el(
    documentNode, "span", "frontier-panel-detail", text,
  ));
}

function scopeLabel(scope, projects) {
  if (scope === "all" || scope === null || scope === undefined) {
    return "across all projects";
  }
  const selected = Array.isArray(scope) ? scope : [scope];
  const byKey = new Map(projects.flatMap((project) => [
    [String(project.id), project],
    [String(project.slug), project],
  ]));
  const labels = selected.map((key) => {
    const project = byKey.get(String(key));
    return String(project?.slug || project?.name || key);
  });
  return `scoped to ${labels.join(" + ")}`;
}

function appendCell(documentNode, row, content, className = null) {
  const cell = el(documentNode, "td", className);
  if (content && typeof content === "object" && content.tagName) {
    cell.appendChild(content);
  } else {
    cell.textContent = String(content ?? "");
  }
  row.appendChild(cell);
}

function itemLink(documentNode, href, label, className = null) {
  const link = el(
    documentNode,
    "a",
    ["row-link", className].filter(Boolean).join(" "),
    label,
  );
  link.href = href;
  return link;
}

function appendItemCell(documentNode, row, item, href) {
  const cell = el(documentNode, "td", "frontier-item");
  const title = itemLink(
    documentNode,
    href,
    item.title || item.item_id,
  );
  title.classList.add("frontier-item-title");
  cell.appendChild(title);
  if (item.title) {
    const ref = el(
      documentNode, "small", "frontier-item-ref mono", item.item_id,
    );
    cell.appendChild(ref);
  }
  row.appendChild(cell);
}

function renderFrontierTable(body, rows, headers, renderRow, emptyText) {
  const documentNode = body.ownerDocument;
  const wrap = el(documentNode, "div", "table-wrap");
  const table = el(documentNode, "table", "items frontier-table");
  const head = el(documentNode, "tr");
  for (const label of headers) head.appendChild(el(documentNode, "th", null, label));
  table.appendChild(head);
  if (!rows.length) {
    const emptyRow = el(documentNode, "tr", "frontier-empty-row");
    const emptyCell = el(documentNode, "td", "frontier-empty empty", emptyText);
    emptyCell.setAttribute("colspan", headers.length);
    emptyRow.appendChild(emptyCell);
    table.appendChild(emptyRow);
  }
  for (const row of rows) {
    const tr = el(documentNode, "tr");
    renderRow(documentNode, tr, row);
    table.appendChild(tr);
  }
  wrap.appendChild(table);
  body.appendChild(wrap);
}

export function renderFrontierView(context, main, scope) {
  const documentNode = context.document;
  const statsHost = el(documentNode, "div", "frontier-stats");
  const readyPanel = section(
    documentNode, "Ready to work", { showRaw: false },
  );
  const blockedPanel = section(
    documentNode, "Blocked", { showRaw: false },
  );
  main.classList.add("frontier-view");
  readyPanel.classList.add("frontier-ready-panel");
  blockedPanel.classList.add("frontier-blocked-panel");
  main.replaceChildren(statsHost, readyPanel, blockedPanel);
  const projects = context.projects();
  const buckets = scopeBuckets(scope, projects, false);
  appendPanelDetail(
    documentNode, readyPanel, scopeLabel(scope, projects),
  );
  appendPanelDetail(
    documentNode, blockedPanel, "why these cannot run yet",
  );
  const idBySlug = new Map(
    projects.map((row) => [String(row.slug), String(row.id)]),
  );
  const projectBySlug = new Map(
    projects.map((row) => [String(row.slug), row]),
  );
  const rowProject = (row) => (
    (Array.isArray(scope) && scope.length === 1)
      ? scope[0]
      : (idBySlug.get(String(row.project)) || String(row.project))
  );
  const itemHref = (row, ref = row.item_id) => buildUniverseRoute(
    "items",
    rowProject(row),
    String(ref || "").replace(/^[A-Za-z]+-/, ""),
  );
  const projectLabel = (row) => {
    const project = projectBySlug.get(String(row.project));
    return [project?.emoji, project?.slug || row.project]
      .filter(Boolean)
      .join(" ");
  };
  const sum = (results, key) => results.reduce(
    (total, callResult) => total +
      (Number((callResult.envelope.result || {})[key]) || 0),
    0,
  );
  let frontierResults = null;
  let liveSessionCount = null;
  const renderStats = () => {
    if (!frontierResults) return;
    const readyRows = mergedRows(
      frontierResults, (result) => result.ready_rows,
    );
    const strip = metricStrip(documentNode, [
      { label: "ready now", value: readyRows.length },
      {
        label: "in progress",
        value: sum(frontierResults, "wip_active"),
      },
      {
        label: "blocked",
        value: mergedRows(
          frontierResults, (result) => result.blocked_rows,
        ).reduce((ids, row) => ids.add(row.item_id), new Set()).size,
      },
      {
        label: "waiting on you",
        value: sum(frontierResults, "waiting_on_you_count"),
      },
    ]);
    if (liveSessionCount !== null) {
      strip.children[1].children[0].appendChild(el(
        documentNode,
        "span",
        "frontier-session-count",
        `· ${liveSessionCount} session${liveSessionCount === 1 ? "" : "s"}`,
      ));
    }
    statsHost.replaceChildren(strip);
  };

  loadScopedPanels(context, [
    [readyPanel, (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.ready_rows);
      readyPanel.setCount("ranked");
      frontierResults = callResults;
      renderStats();
      const headers = [
        "", "item", "Type", "project", "progress",
        "why it is ready", "run in your harness",
      ];
      renderFrontierTable(body, rows, headers, (doc, tr, row) => {
        tr.classList.add("frontier-ready-row");
        appendCell(
          doc,
          tr,
          el(
            doc,
            "span",
            "frontier-rank",
            typeof row.rank === "number" ? row.rank + 1 : row.rank,
          ),
          "frontier-rank-cell",
        );
        appendItemCell(doc, tr, row, itemHref(row));
        appendCell(doc, tr, workflowBadge(doc, row.workflow_id));
        appendCell(doc, tr, projectLabel(row), "frontier-project");
        appendCell(doc, tr, stageProgress(
          doc, row.stage_index, row.stage_count,
        ));
        appendCell(
          doc,
          tr,
          el(doc, "div", "frontier-why", row.why_ready),
          "frontier-why-cell",
        );
        const command = el(
          doc, "code", "frontier-command", row.run_command || "",
        );
        appendCell(doc, tr, command, "frontier-command-cell");
      }, "No ready work in this scope.");
    }],
    [blockedPanel, (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.blocked_rows);
      const uniqueItems = new Set(rows.map((row) => row.item_id));
      blockedPanel.setCount(uniqueItems.size);
      const headers = [
        "item", "project", "waiting on", "why", "gate",
      ];
      renderFrontierTable(body, rows, headers, (doc, tr, row) => {
        tr.classList.add("frontier-blocked-row");
        appendItemCell(doc, tr, row, itemHref(row));
        appendCell(doc, tr, projectLabel(row), "frontier-project");
        appendCell(
          doc,
          tr,
          row.blocking_item
            ? itemLink(
              doc,
              itemHref(row, row.blocking_item),
              row.blocking_item,
              "mono",
            )
            : "—",
          "frontier-waiting-on",
        );
        appendCell(
          doc,
          tr,
          el(doc, "div", "frontier-why", row.why),
          "frontier-why-cell",
        );
        appendCell(doc, tr, statePill(doc, row.gate_point, row.gate_point));
      }, "Nothing blocked in this scope.");
    }],
  ], buckets.map((bucket) => ({
    functionId: "frontier.list",
    payload: bucket === null ? {} : { project: bucket },
  })));

  void settledScopedCalls(
    context,
    buckets.flatMap((bucket) => LIVE_SESSION_STATES.map((liveness) => ({
      functionId: "sessions.list",
      payload: {
        ...(bucket === null ? {} : { project: bucket }),
        liveness,
        limit: 500,
      },
    }))),
  ).then(({ callResults, failed }) => {
    if (!context.isMounted() || failed) return;
    const rows = mergedRows(callResults, (result) => result.rows);
    liveSessionCount = new Set(rows.filter(
      (row) => row.owns_current_item === true,
    ).map(
      (row, index) => row.session_id || `unidentified-${index}`,
    )).size;
    renderStats();
  });
}
