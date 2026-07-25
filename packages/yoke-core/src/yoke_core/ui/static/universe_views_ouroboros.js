import {
  loadScopedSection,
  mergedRows,
  renderTable,
  scopeBuckets,
  section,
  withProjectColumn,
} from "./universe_view_support.js";

// What the system noticed about itself, and what came of it. `reviewed_at` is
// the second half of that sentence: an observation nobody has looked at yet is
// not the same as one that has been through curation, and a row that hid the
// difference would make the loop look closed when it is still open.
export function renderOuroborosView(context, main, scope) {
  const panel = section(context.document, "Ouroboros");
  main.replaceChildren(panel);
  // The entry read is project-scoped and refuses a call that names no
  // project, so "all" fans out into one call per roster project rather than
  // one unfiltered call.
  const buckets = scopeBuckets(scope, context.projects(), true);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "ouroboros.entry.list",
      payload: { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.entries);
      // The count is the bounded receipt set fetched for this scope.
      panel.setCount(rows.length);
      // Each entry carries the slug of the project it observed — a
      // universe-level observation carries none and shows none.
      renderTable(body, rows, withProjectColumn([
        { label: "when", value: (row) => row.timestamp },
        { label: "category", value: (row) => row.category, pill: true },
        { label: "agent", value: (row) => row.agent },
        { label: "context", value: (row) => row.context },
        {
          label: "reviewed",
          value: (row) => (row.reviewed_at ? row.reviewed_at : ""),
        },
      ], scope, (row) => row.project), "nothing noticed yet");
    },
  );
}
