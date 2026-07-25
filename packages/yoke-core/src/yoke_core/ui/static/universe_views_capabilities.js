import {
  loadScopedSection,
  mergedRows,
  renderTable,
  scopeBuckets,
  section,
  withProjectColumn,
} from "./universe_view_support.js";

// What Yoke can reach on a project's behalf, and how honestly it can claim
// so. The engine owns the vocabulary end to end: the capability column shows
// the STORED type string (never an invented label), kind/state arrive
// derived, and the verified stamp is whichever source the engine trusts for
// that type (the GitHub row wears its repo-binding freshness). A NULL stamp
// renders as the word "never" — configured-but-never-verified is a warning,
// not a resting state.
export function renderCapabilitiesView(context, main, scope) {
  const panel = section(context.document, "Capabilities");
  main.replaceChildren(panel);
  const buckets = scopeBuckets(scope, context.projects(), false);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "projects.capabilities.list",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.rows);
      // Each capability row carries the slug of the project declaring it.
      renderTable(body, rows, withProjectColumn([
        { label: "capability", value: (row) => row.type, mono: true },
        { label: "kind", value: (row) => row.kind, pill: true },
        { label: "settings", value: (row) => row.settings_summary || "—" },
        { label: "verified", value: (row) => row.verified_at || "never" },
        { label: "state", value: (row) => row.state, pill: true },
      ], scope, (row) => row.project), "no capabilities declared yet");
    },
  );
}
