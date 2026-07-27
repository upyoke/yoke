import { buildUniverseRoute } from "./universe_navigation.js";
import {
  el,
  mergedRows,
  renderError,
  scopeBuckets,
  section,
  settledScopedCalls,
  statePill,
  withProjectColumn,
} from "./universe_view_support.js";
import { actionLink } from "./item_view_primitives.js";
export { renderItemDetailView } from "./item_detail_loader.js";

function detailProject(scope, projects) {
  if (Array.isArray(scope)) return scope[0] || null;
  if (scope === "all") return projects[0] ? String(projects[0].id) : null;
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

function claimLabel(row) {
  const claim = row.claimed_by;
  return claim ? (claim.actor_label || claim.session_id || "") : "";
}

function projectLabel(projects, row) {
  const rowLabel = row.project_slug || row.project;
  const rowKey = row.project_id ?? rowLabel;
  const project = projects.find((candidate) => (
    [candidate.id, candidate.slug, candidate.name].some(
      (value) => String(value) === String(rowKey),
    )
  ));
  return String(
    rowLabel || project?.slug || project?.name || row.project_id || "—",
  );
}

function eventCameFromControl(event, row) {
  let target = event.target;
  while (target && target !== row) {
    if (["A", "BUTTON", "INPUT", "SELECT", "TEXTAREA", "TIME"].includes(
      String(target.tagName || "").toUpperCase(),
    )) return true;
    target = target.parentNode;
  }
  return false;
}

function makeRowNavigable(documentNode, row, href) {
  row.tabIndex = 0;
  row.setAttribute("role", "link");
  row.setAttribute("aria-label", `Open ${row.children[0]?.textContent || "item"}`);
  row.addEventListener("click", (event) => {
    if (eventCameFromControl(event, row)) return;
    documentNode.defaultView.location.hash = href;
  });
  row.addEventListener("keydown", (event) => {
    if (eventCameFromControl(event, row)) return;
    if (!["Enter", " "].includes(event.key)) return;
    if (typeof event.preventDefault === "function") event.preventDefault();
    documentNode.defaultView.location.hash = href;
  });
}

function itemTable(documentNode, rows, rowHref, scope, projects) {
  if (!rows.length) {
    return el(documentNode, "p", "empty", "No items match this view.");
  }
  const table = el(documentNode, "table", "items item-roster");
  const columns = withProjectColumn([
    { label: "ID" },
    { label: "Title" },
    { label: "Workflow" },
    { label: "Status" },
    { label: "Owner" },
    { label: "Claimed by" },
  ], scope, (row) => projectLabel(projects, row));
  const projectColumn = columns.find((column) => column.label === "project");
  const head = el(documentNode, "tr");
  for (const column of columns) {
    head.appendChild(el(documentNode, "th", null, column.label));
  }
  table.appendChild(head);
  for (const row of rows) {
    const href = rowHref(row);
    const tr = el(documentNode, "tr", "item-roster-row");
    const refCell = el(documentNode, "td", "mono");
    const link = el(documentNode, "a", "row-link", row.public_ref);
    link.href = href;
    refCell.appendChild(link);
    tr.appendChild(refCell);
    if (projectColumn) {
      tr.appendChild(el(
        documentNode,
        "td",
        "item-project",
        projectColumn.value(row),
      ));
    }
    const titleCell = el(documentNode, "td", "item-roster-title");
    const titleLink = el(
      documentNode, "a", "item-title-link", row.title,
    );
    titleLink.href = href;
    titleCell.appendChild(titleLink);
    tr.appendChild(titleCell);
    const workflowCell = el(documentNode, "td");
    const workflow = el(
      documentNode,
      "span",
      `item-workflow ${String(row.workflow_id || "").toLowerCase()}`,
      row.workflow_id,
    );
    workflow.setAttribute("data-workflow", row.workflow_id);
    workflow.setAttribute("title", `workflow · ${row.workflow_id}`);
    workflowCell.appendChild(workflow);
    tr.appendChild(workflowCell);
    const statusCell = el(documentNode, "td");
    const status = statePill(
      documentNode,
      row.status,
      row.stage_label || row.status,
    );
    if (status) statusCell.appendChild(status);
    tr.appendChild(statusCell);
    tr.appendChild(el(
      documentNode,
      "td",
      "item-muted",
      row.owner || "unassigned",
    ));
    const claimCell = el(documentNode, "td", "item-muted");
    const claimedBy = claimLabel(row);
    if (claimedBy) {
      claimCell.appendChild(el(
        documentNode,
        "span",
        "item-claim-avatar",
        claimedBy.slice(0, 1).toUpperCase(),
      ));
      claimCell.appendChild(el(
        documentNode, "span", null, claimedBy,
      ));
    } else {
      claimCell.textContent = "—";
    }
    tr.appendChild(claimCell);
    makeRowNavigable(documentNode, tr, href);
    table.appendChild(tr);
  }
  const wrap = el(documentNode, "div", "table-wrap item-roster-wrap");
  wrap.appendChild(table);
  return wrap;
}

function filterRows(rows, state) {
  const query = state.query.trim().toLowerCase();
  return rows.filter((row) => {
    if (state.workflow && row.workflow_id !== state.workflow) return false;
    if (state.status && row.status !== state.status) return false;
    if (!query) return true;
    return [
      row.public_ref, row.title, row.owner, claimLabel(row),
    ].some((value) => String(value || "").toLowerCase().includes(query));
  });
}

function filterControls(documentNode, rows, state, rerender) {
  const controls = el(documentNode, "div", "item-filters");
  const query = el(documentNode, "input", "item-filter-control");
  query.type = "search";
  query.placeholder = "ID, title, owner, or claim";
  query.value = state.query;
  query.addEventListener("input", () => {
    state.query = query.value;
    rerender();
  });
  controls.appendChild(query);
  for (const [key, label] of [
    ["workflow", "All workflows"],
    ["status", "All statuses"],
  ]) {
    const select = el(documentNode, "select", "item-filter-control");
    const empty = el(documentNode, "option", null, label);
    empty.value = "";
    select.appendChild(empty);
    const rowKey = key === "workflow" ? "workflow_id" : key;
    const valueLabels = new Map();
    for (const row of rows) {
      const value = row[rowKey];
      if (!value || valueLabels.has(value)) continue;
      valueLabels.set(
        value,
        key === "status" ? row.stage_label || value : value,
      );
    }
    const values = [...valueLabels.keys()].sort((left, right) => (
      String(valueLabels.get(left)).localeCompare(
        String(valueLabels.get(right)),
      )
    ));
    for (const value of values) {
      const option = el(
        documentNode, "option", null, valueLabels.get(value),
      );
      option.value = value;
      option.selected = state[key] === value;
      select.appendChild(option);
    }
    select.value = state[key];
    select.addEventListener("change", () => {
      state[key] = select.value;
      rerender();
    });
    controls.appendChild(select);
  }
  return controls;
}

export function renderItemsView(context, main, scope, chrome = {}) {
  const documentNode = context.document;
  const projects = context.projects();
  const panel = section(documentNode, "Items", { showRaw: false });
  const filterButton = el(documentNode, "button", "item-button", "Filter ▾");
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
  if (typeof chrome.setPageHead === "function") {
    chrome.setPageHead({
      title: "Items",
      summary: itemsScopeSummary(scope, projects),
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
  const filterState = {
    open: false,
    query: "",
    workflow: "",
    status: "",
  };
  filterButton.addEventListener("click", () => {
    filterState.open = !filterState.open;
    filterHost.hidden = !filterState.open;
    filterButton.setAttribute("aria-expanded", String(filterState.open));
  });
  filterHost.hidden = true;

  const buckets = scopeBuckets(scope, projects, false);
  const calls = buckets.map((bucket) => ({
      functionId: "items.overview.list",
      payload: bucket === null ? {} : { project: bucket },
    }));
  const renderPrototype = (callResults) => {
    panel.renderEnvelopes(callResults, (body) => {
      const rows = mergedRows(callResults, (result) => result.rows);
      const counts = callResults.map(
        (callResult) => (callResult.envelope.result || {}).count,
      );
      panel.setCount(
        counts.every((count) => typeof count === "number")
          ? counts.reduce((total, count) => total + count, 0)
          : null,
      );
      const renderRows = () => {
        body.replaceChildren(itemTable(
          documentNode,
          filterRows(rows, filterState),
          (row) => buildUniverseRoute(
            "items",
            String(row.project_id),
            String(row.public_ref),
          ),
          scope,
          projects,
        ));
      };
      filterHost.replaceChildren(filterControls(
        documentNode, rows, filterState, renderRows,
      ));
      filterHost.hidden = !filterState.open;
      renderRows();
    });
  };
  settledScopedCalls(context, calls).then(({ callResults, failed }) => {
    if (!context.isMounted()) return;
    if (!failed) {
      renderPrototype(callResults);
      return;
    }
    panel.renderEnvelope(failed, (body) => renderError(body, failed));
  });
}
