import { renderMarkdown } from "./markdown_view.js";
import { itemDrillInHref } from "./universe_item_routes.js";
import { buildUniverseRoute } from "./universe_navigation.js";
import {
  callFunction,
  el,
  loadSection,
  renderError,
  renderTable,
  section,
  withProjectColumn,
} from "./universe_view_support.js";
import { actionLink } from "./item_view_primitives.js";

import { createOuroborosLoader } from "./ouroboros_roster_loader.js";
import { sortHeader } from "./item_roster_sort.js";
import { OUROBOROS_SORT_COLUMNS } from "./ouroboros_roster_sort.js";
export { OUROBOROS_PAGE_SIZE } from "./ouroboros_roster_loader.js";

function promotedRef(row) {
  return row.promoted_dash?.public_ref || row.promoted_dash?.item_ref || "";
}

function ouroborosFilters(documentNode, loader) {
  const host = el(documentNode, "div", "item-filters");
  const review = el(documentNode, "select", "item-filter-control");
  review.setAttribute("aria-label", "Review state");
  for (const [value, label] of [
    ["all", "All observations"],
    ["unreviewed", "Unreviewed"],
    ["reviewed", "Reviewed"],
  ]) {
    const option = el(documentNode, "option", null, label);
    option.value = value;
    if (value === "all") option.selected = true;
    review.appendChild(option);
  }
  review.addEventListener("change", () => loader.setReviewState(review.value));
  const prefix = el(documentNode, "input", "item-filter-control");
  prefix.type = "text";
  prefix.placeholder = "Category prefix";
  prefix.setAttribute("aria-label", "Category prefix");
  prefix.addEventListener("change", () => {
    loader.setCategoryPrefix(prefix.value.trim());
  });
  host.appendChild(review);
  host.appendChild(prefix);
  return host;
}

export function renderOuroborosView(context, main, scope) {
  const documentNode = context.document;
  const panel = section(documentNode, "Ouroboros");
  const loaded = el(documentNode, "p", "item-muted ouroboros-loaded-count");
  let loader;
  const renderState = (state) => {
    if (!context.isMounted()) return;
    if (state.failure && !state.rows.length) {
      panel.setCount(null);
      loaded.textContent = "";
      panel.renderEnvelope(state.failure, (body) => {
        renderError(body, state.failure);
        const button = el(documentNode, "button", "item-button", "Retry");
        button.type = "button";
        button.addEventListener("click", () => loader.start());
        body.appendChild(button);
      });
      return;
    }
    panel.setCount(state.matchingCount);
    loaded.textContent = typeof state.matchingCount === "number"
      ? `${state.loadedCount} loaded of ${state.matchingCount} matching`
      : `${state.loadedCount} loaded`;
    if (state.sortNotice) loaded.textContent += `. ${state.sortNotice}`;
    panel.renderEnvelopes([], (body) => {
      if (state.loading && !state.rows.length) {
        body.appendChild(el(documentNode, "p", "empty", "loading…"));
        return;
      }
      renderTable(body, state.rows, withProjectColumn([
        { label: "Observation", value: (row) => row.preview || row.context || `Field note #${row.id}` },
        { label: "Filed at", value: (row) => row.timestamp },
        { label: "Category", value: (row) => row.category, pill: true },
        { label: "Context", value: (row) => row.context },
        {
          label: "Reviewed",
          value: (row) => (row.reviewed_at ? row.reviewed_at : ""),
        },
        {
          label: "promoted work",
          value: (row) => promotedRef(row),
          href: (row) => row.promoted_dash
            ? itemDrillInHref({
              projectId: row.promoted_dash.project_id,
              publicRef: promotedRef(row),
            })
            : null,
        },
      ], scope, (row) => row.project).map(column => ({
        ...column,
        ...(OUROBOROS_SORT_COLUMNS[column.label] ? {
          header: () => sortHeader(documentNode, column.label, state.criteria.sort, key => loader.setSort(key), OUROBOROS_SORT_COLUMNS[column.label]),
        } : {}),
      })), "nothing noticed yet", (row) => (
        buildUniverseRoute(
          "ouroboros",
          row.project || (Array.isArray(scope) ? scope[0] : scope),
          String(row.id),
        )
      ), { stack: true, sortable: true, className: "ouroboros-roster" });
      const more = el(documentNode, "div", "item-roster-more");
      if (state.failure) renderError(more, state.failure);
      if (state.hasMore || state.failure) {
        const button = el(
          documentNode,
          "button",
          "item-button",
          state.failure
            ? (state.rows.length ? "Retry load more" : "Retry")
            : (state.loading ? "Loading…" : "Load more"),
        );
        button.type = "button";
        button.disabled = state.loading;
        button.addEventListener("click", () => {
          if (!state.rows.length) loader.start();
          else loader.loadMore();
        });
        more.appendChild(button);
      }
      body.appendChild(more);
    });
  };
  loader = createOuroborosLoader({ context, scope, onChange: renderState });
  main.replaceChildren(ouroborosFilters(documentNode, loader), loaded, panel);
  loader.start();
}

export function renderOuroborosEntryDetailView(
  context,
  main,
  projectId,
  entryId,
  navigation = {},
) {
  const documentNode = context.document;
  const panel = section(documentNode, `Field note #${entryId}`);
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
          promotedRef(entry),
          itemDrillInHref({
            projectId: entry.promoted_dash.project_id,
            publicRef: promotedRef(entry),
          }),
        ));
        body.appendChild(outcome);
      }
    },
  );
}
