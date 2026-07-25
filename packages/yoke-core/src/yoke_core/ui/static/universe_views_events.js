import {
  loadScopedSection,
  mergedRows,
  renderTable,
  scopeBuckets,
  section,
  withProjectColumn,
} from "./universe_view_support.js";

export function renderEventsView(context, main, scope) {
  const panel = section(context.document, "Events");
  main.replaceChildren(panel);
  // The events read is project-scoped and refuses a call that names no
  // project, so "all" fans out into one call per roster project rather than
  // one unfiltered call.
  const buckets = scopeBuckets(scope, context.projects(), true);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "events.query.run",
      payload: { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.rows);
      // The fan-out returns one block per project; the pulse is one stream,
      // so the merged rows re-sort newest-first across all buckets.
      const at = (row) => Date.parse(row.created_at) || 0;
      rows.sort((a, b) => at(b) - at(a));
      // No header count here: only a served total or a known-complete set
      // earns one, and this read attests neither.
      // Each event row carries the slug of the project it was recorded
      // against — a universe-level event carries none and shows none.
      renderTable(body, rows, withProjectColumn([
        { label: "when", value: (row) => row.created_at },
        { label: "event", value: (row) => row.event_name },
        { label: "kind", value: (row) => row.event_kind },
        { label: "severity", value: (row) => row.severity, pill: true },
        {
          label: "source",
          // A bare integer reads as data noise; say what the number is.
          value: (row) => (
            row.actor_id !== null && row.actor_id !== undefined
              ? `actor ${row.actor_id}` : (row.service || "")
          ),
        },
      ], scope, (row) => row.project), "no events yet");
    },
  );
}
