import { renderMarkdown } from "./markdown_view.js";
import { buildUniverseRoute } from "./universe_navigation.js";
import {
  el,
  loadScopedSection,
  loadSection,
  mergedRows,
  renderTable,
  scopeBuckets,
  section,
  withProjectColumn,
} from "./universe_view_support.js";
import { actionLink } from "./item_view_primitives.js";

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
        {
          label: "promoted work",
          value: (row) => row.promoted_dash?.item_ref || "",
          href: (row) => row.promoted_dash
            ? buildUniverseRoute(
              "items",
              row.promoted_dash.project_id,
              row.promoted_dash.item_ref,
            )
            : null,
        },
      ], scope, (row) => row.project), "nothing noticed yet");
    },
  );
}

export function renderOuroborosEntryDetailView(
  context,
  main,
  projectId,
  entryId,
  navigation = {},
) {
  const documentNode = context.document;
  const panel = section(
    documentNode, `Field note #${entryId}`, { showRaw: false },
  );
  main.replaceChildren(panel);
  loadSection(
    context,
    panel,
    "ouroboros.entry.get",
    { entry_id: Number(entryId), project: String(projectId) },
    (body, callResult) => {
      const entry = (callResult.envelope.result || {}).entry || {};
      if (typeof navigation.setDetailLabel === "function") {
        navigation.setDetailLabel(`Field note #${entry.id || entryId}`);
      }
      const contextLine = [
        entry.category,
        entry.agent ? `noticed by ${entry.agent}` : "",
        entry.context || "",
      ].filter(Boolean).join(" · ");
      body.appendChild(el(
        documentNode, "p", "item-muted", contextLine,
      ));
      body.appendChild(renderMarkdown(documentNode, entry.body, {
        className: "rich-text item-prose",
        emptyText: "No evidence recorded.",
        demoteHeadings: true,
      }));
      if (entry.promoted_dash) {
        const outcome = el(documentNode, "div", "item-detail-state");
        outcome.appendChild(el(
          documentNode, "span", "item-muted", "Promoted to",
        ));
        outcome.appendChild(actionLink(
          documentNode,
          entry.promoted_dash.item_ref,
          buildUniverseRoute(
            "items",
            entry.promoted_dash.project_id,
            entry.promoted_dash.item_ref,
          ),
        ));
        body.appendChild(outcome);
      }
    },
  );
}
