import { buildUniverseRoute } from "./universe_navigation.js";
import { itemDrillInHref } from "./universe_item_routes.js";
import {
  el,
  renderError,
  section,
} from "./universe_view_support.js";
import { actionLink } from "./item_view_primitives.js";
import { createRosterLoader } from "./universe_items_roster_loader.js";
import { itemTable } from "./item_roster_table.js";
export { renderItemDetailView } from "./item_detail_loader.js";

function detailProject(scope, projects) {
  if (Array.isArray(scope)) return scope.length === 1 ? scope[0] : null;
  if (scope === "all") return projects.length === 1 ? String(projects[0].id) : null;
  return scope;
}

function itemsScopeSummary(scope, projects) {
  if (scope === "all" || scope === null) {
    return "across all projects · every durable piece of project work";
  }
  const selected = Array.isArray(scope) ? scope : [scope];
  const labels = selected.map((projectId) => {
    const project = projects.find(
      (candidate) => String(candidate.id) === String(projectId),
    );
    return project?.slug || project?.name || String(projectId);
  });
  return `scoped to ${labels.join(" + ")} · every durable piece of project work`;
}

// Built once and updated in place. Rebuilding the controls on every response
// would take the focus and caret out of the search box on the very keystroke
// that triggered the reload.
function filterControls(documentNode, loader) {
  const controls = el(documentNode, "div", "item-filters");
  const query = el(documentNode, "input", "item-filter-control");
  query.type = "search";
  query.setAttribute("aria-label", "Search items by ID, title, owner, or claim");
  query.placeholder = "ID, title, owner, or claim";
  query.addEventListener("input", () => loader.setQuery(query.value));
  controls.appendChild(query);
  const selects = new Map();
  for (const [key, emptyLabel] of [
    ["workflow", "All workflows"],
    ["status", "All statuses"],
  ]) {
    const select = el(documentNode, "select", "item-filter-control");
    select.setAttribute("aria-label", emptyLabel);
    select.addEventListener(
      "change", () => loader.setFilter(key, select.value),
    );
    selects.set(key, { select, emptyLabel, signature: null });
    controls.appendChild(select);
  }
  // Choices come from the server for the whole scope, so they stay complete
  // instead of shrinking to whatever the current page happens to contain.
  const update = (state) => {
    const choices = {
      workflow: (state.filters.workflow_ids || []).map(
        (id) => ({ id, label: id }),
      ),
      status: state.filters.statuses || [],
    };
    for (const [key, entry] of selects) {
      const signature = JSON.stringify(choices[key]);
      if (entry.signature !== signature) {
        entry.signature = signature;
        const empty = el(documentNode, "option", null, entry.emptyLabel);
        empty.value = "";
        const options = [empty];
        for (const choice of choices[key]) {
          const option = el(documentNode, "option", null, choice.label);
          option.value = choice.id;
          options.push(option);
        }
        entry.select.replaceChildren(...options);
      }
      for (const option of entry.select.children) {
        option.selected = option.value === state.criteria[key];
      }
      entry.select.value = state.criteria[key];
    }
  };
  return { node: controls, update };
}

export function renderItemsView(context, main, scope, chrome = {}) {
  const documentNode = context.document;
  const projects = context.projects();
  const panel = section(documentNode, "Items");
  const filterButton = el(documentNode, "button", "item-button item-roster-action item-filter-toggle", "Filter");
  const chevron = el(documentNode, "span", "band-chevron");
  chevron.setAttribute("aria-hidden", "true");
  filterButton.appendChild(chevron);
  filterButton.type = "button";
  filterButton.setAttribute("aria-expanded", "false");
  filterButton.setAttribute("aria-controls", "item-roster-filters");
  const projectId = detailProject(scope, projects);
  const newItem = actionLink(
    documentNode,
    "New item",
    buildUniverseRoute("items", projectId, "new"),
    true,
  );
  newItem.classList.add("item-roster-action");
  if (typeof chrome.setPageHead === "function") {
    chrome.setPageHead({
      title: "Items",
      actions: [filterButton, newItem],
    });
  }
  const filterHost = el(documentNode, "div");
  filterHost.id = "item-roster-filters";
  if (typeof chrome.setPageHead === "function") {
    main.replaceChildren(filterHost, panel);
  } else {
    const toolbar = el(documentNode, "div", "item-roster-toolbar");
    toolbar.appendChild(el(
      documentNode,
      "p",
      "item-roster-note",
      itemsScopeSummary(scope, projects),
    ));
    const actions = el(documentNode, "div", "item-roster-actions");
    actions.appendChild(filterButton);
    actions.appendChild(newItem);
    toolbar.appendChild(actions);
    main.replaceChildren(toolbar, filterHost, panel);
  }
  let filtersOpen = false;
  let sortFocus = null;
  filterButton.addEventListener("click", () => {
    filtersOpen = !filtersOpen;
    filterHost.hidden = !filtersOpen;
    filterButton.setAttribute("aria-expanded", String(filtersOpen));
  });

  const loader = createRosterLoader({
    context,
    scope,
    onChange: (state) => renderState(state),
  });
  const controls = filterControls(documentNode, loader);
  filterHost.replaceChildren(controls.node);
  filterHost.hidden = true;

  function renderState(state) {
    if (!context.isMounted()) return;
    // A failure with nothing on screen replaces the table; a failure while
    // rows are already rendered is reported beside them. Discarding fetched
    // rows because the NEXT page failed is worse than never having asked.
    if (state.failure && !state.rows.length) {
      panel.renderEnvelope(
        state.failure, (body) => {
          renderError(body, state.failure);
          if (state.sortNotice) body.appendChild(el(documentNode, "p", "error-banner", state.sortNotice));
        },
      );
      return;
    }
    // The total behind the page, not the page's own length: the roster's
    // heading reports how much matches, not how much has loaded.
    panel.setCount(state.matchCount);
    controls.update(state);
    panel.renderEnvelopes([], (body) => {
      if (state.loading && !state.rows.length) {
        body.appendChild(el(documentNode, "p", "empty", "loading…"));
        return;
      }
      body.appendChild(itemTable(
        documentNode,
        state.rows,
        (row) => itemDrillInHref({
          projectId: row.project_id,
          publicRef: row.public_ref,
        }),
        scope,
        projects, state.criteria.sort,
        (column) => { sortFocus = column; loader.setSort(column); },
      ));
      if (!state.loading && sortFocus) {
        body.querySelector?.(`[data-sort-column="${sortFocus}"]`)?.focus?.();
        sortFocus = null;
      }
      if (state.sortNotice) body.appendChild(el(documentNode, "p", "error-banner", state.sortNotice));
      if (!state.hasMore && !state.failure) return;
      const more = el(documentNode, "div", "item-roster-more");
      if (state.failure) renderError(more, state.failure);
      if (state.hasMore) {
        const button = el(
          documentNode,
          "button",
          "item-button",
          state.loading ? "Loading…" : "Load more",
        );
        button.type = "button";
        button.disabled = state.loading;
        button.addEventListener("click", () => { loader.loadMore(); });
        more.appendChild(button);
      }
      body.appendChild(more);
    });
  }

  loader.start();
}
