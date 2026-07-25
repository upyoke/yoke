import {
  loadScopedSection,
  mergedRows,
  renderTable,
  scopeBuckets,
  section,
  whoColumn,
  withProjectColumn,
} from "./universe_view_support.js";

// The session, not the item: who runs (the actor, honestly labelled by the
// engine so a system actor never reads as a person), what it holds (its
// active work-claims, rendered server-side from the typed targets), how
// alive it is (engine-derived liveness — the executor-aware TTL numbers
// live in the engine, never here), and what Yoke directed it to do (the
// stored execution lane and mode).
export function renderSessionsView(context, main, scope) {
  const panel = section(context.document, "Sessions");
  main.replaceChildren(panel);
  const buckets = scopeBuckets(scope, context.projects(), false);
  // Who runs a session is the actor by default; a host that names accounts
  // (a hosted org) turns the same column into the member it maps to.
  const who = whoColumn(context.capabilities);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "sessions.list",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.rows);
      // Every bucket served its complete set, so the merged length is the
      // fetched total.
      panel.setCount(rows.length);
      // Each session row carries the slug of the project it works in.
      renderTable(body, rows, withProjectColumn([
        { label: "session", value: (row) => row.session_id },
        { label: who.label, value: who.value },
        { label: "liveness", value: (row) => row.liveness, pill: true },
        { label: "lane", value: (row) => row.execution_lane },
        { label: "mode", value: (row) => row.mode },
        {
          label: "holds",
          value: (row) => (row.claims || [])
            .map((claim) => claim.target).join(", "),
        },
        { label: "item", value: (row) => row.current_item },
        { label: "last activity", value: (row) => row.activity_at },
      ], scope, (row) => row.project), "no sessions yet");
    },
  );
}
