import {
  loadScopedSection,
  mergedRows,
  renderTable,
  scopeBuckets,
  section,
  withProjectColumn,
} from "./universe_view_support.js";

// Each run of a flow against a target environment. The engine owns the run's
// vocabulary: status colors through the pill hint (a run halted for approval
// keeps status "executing" and so stays a running pill, never a failed one),
// and the stage shows as the text the engine recorded — the stage roster
// belongs to the flow definition, so nothing here hardcodes its shape.
export function renderDeliveryRunsView(context, main, scope) {
  const panel = section(context.document, "Runs");
  main.replaceChildren(panel);
  const buckets = scopeBuckets(scope, context.projects(), false);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "deployment_runs.list",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      // The engine bounds run history and returns the newest receipts first.
      const rows = mergedRows(callResults, (result) => result.rows);
      // Every bucket served its complete set, so the merged length is the
      // fetched total.
      panel.setCount(rows.length);
      // Each run row carries the slug of the project whose flow ran.
      renderTable(body, rows, withProjectColumn([
        { label: "run", value: (row) => row.id },
        { label: "flow", value: (row) => row.flow },
        { label: "target", value: (row) => row.target_env },
        { label: "stage", value: (row) => row.current_stage },
        { label: "status", value: (row) => row.status, pill: true },
        { label: "created", value: (row) => row.created_at },
      ], scope, (row) => row.project), "no runs yet");
    },
  );
}

// The pipeline definitions runs execute. The same read that serves the
// lifecycle definition (`workflows.definition.get`) also serves the declared
// deployment flows, and a flow belongs to exactly one project — so this facet
// takes the Delivery scope and fans out the way every other multi view does,
// rather than borrowing the lifecycle screen's universe-wide shape.
export function renderDeliveryFlowsView(context, main, scope) {
  const panel = section(context.document, "Flows");
  main.replaceChildren(panel);
  const buckets = scopeBuckets(scope, context.projects(), false);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "workflows.definition.get",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.flows);
      // Every bucket served its complete set, so the merged length is the
      // fetched total.
      panel.setCount(rows.length);
      // Each flow row carries the slug of the project that declares it.
      renderTable(body, rows, withProjectColumn([
        { label: "flow", value: (row) => row.id, mono: true },
        { label: "name", value: (row) => row.name },
        { label: "target env", value: (row) => row.target_env },
        { label: "status", value: (row) => row.status, pill: true },
        {
          label: "stages",
          value: (row) => (row.stage_names || []).join(" → "),
        },
        { label: "on failure", value: (row) => row.on_failure },
      ], scope, (row) => row.project), "no deployment flows declared");
    },
  );
}
