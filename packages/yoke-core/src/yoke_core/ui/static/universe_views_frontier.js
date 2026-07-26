import { buildUniverseRoute } from "./universe_navigation.js";
import {
  loadScopedPanels,
  mergedRows,
  renderTable,
  scopeBuckets,
  section,
} from "./universe_view_support.js";

// What runs next and why, and what a waiting item waits on. One read serves
// both panels: the engine's ranked ready steps — rank is the engine's own,
// never a display index — and one blocked row per unsatisfied dependency
// edge across every gate point (activation stops a start, integration only
// orders the landing, closure holds the closeout), plus the non-edge waits
// (operator blocks) whose gate cell is honestly empty. There is no progress
// column: no per-item done/total exists in the engine, so none is invented
// here. Frontier rows point at items — the item cell links to the items
// drill-in rather than making the row a frontier drill-in of its own.
export function renderFrontierView(context, main, scope) {
  const documentNode = context.document;
  const readyPanel = section(documentNode, "Ready");
  const blockedPanel = section(documentNode, "Blocked");
  main.replaceChildren(readyPanel, blockedPanel);
  const projects = context.projects();
  const buckets = scopeBuckets(scope, projects, false);
  const idBySlug = new Map(
    projects.map((row) => [String(row.slug), String(row.id)]),
  );
  // A row's item link carries the row's own project: at exactly one project
  // the scope id is that project; otherwise the roster maps the served slug
  // back to the id the route speaks.
  const rowProject = (row) => (
    (Array.isArray(scope) && scope.length === 1)
      ? scope[0]
      : (idBySlug.get(String(row.project)) || String(row.project))
  );
  // The items drill-in speaks bare numeric refs; frontier rows carry YOK-N.
  const itemHref = (row) => buildUniverseRoute(
    "items", rowProject(row), String(row.item_id).replace(/^YOK-/, ""),
  );
  // Exactly one project needs no project column; the column keeps its
  // declared position (beside workflow), so the shared leading-cell insertion
  // helper does not apply here.
  const scopedColumns = (columns) => (
    (Array.isArray(scope) && scope.length === 1)
      ? columns.filter((column) => column.label !== "project")
      : columns
  );
  loadScopedPanels(context, [
    [readyPanel, (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.ready_rows);
      renderTable(body, rows, scopedColumns([
        {
          label: "rank",
          // Ordinal display of the engine's own zero-based rank — "1" is
          // the engine's top pick, not a display index (raw JSON keeps
          // the served number).
          value: (row) => (
            typeof row.rank === "number" ? row.rank + 1 : row.rank
          ),
        },
        { label: "item", value: (row) => row.item_id, href: itemHref },
        { label: "workflow", value: (row) => row.workflow_id },
        { label: "version", value: (row) => row.workflow_version },
        { label: "project", value: (row) => row.project },
        { label: "status", value: (row) => row.status, pill: true },
        { label: "priority", value: (row) => row.priority },
        { label: "next step", value: (row) => row.next_step },
        { label: "run command", value: (row) => row.run_command, code: true },
        { label: "why ready", value: (row) => row.why_ready },
      ]), "nothing ready to run");
    }],
    [blockedPanel, (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.blocked_rows);
      renderTable(body, rows, scopedColumns([
        { label: "item", value: (row) => row.item_id },
        { label: "project", value: (row) => row.project },
        { label: "waiting on", value: (row) => row.blocking_item, code: true },
        { label: "gate", value: (row) => row.gate_point, pill: true },
        { label: "why", value: (row) => row.why },
      ]), "nothing waiting");
    }],
  ], buckets.map((bucket) => ({
    functionId: "frontier.list",
    payload: bucket === null ? {} : { project: bucket },
  })));
}
