import { buildUniverseRoute } from "./universe_navigation.js";
import {
  callFunction,
  el,
  mergedRows,
  renderError,
  scopeBuckets,
  section,
  settledScopedCalls,
  statePill,
} from "./universe_view_support.js";
import { renderWorkflowItemDetail } from "./item_view_details.js";
import { renderBlitzItemDetail } from "./universe_views_blitz.js";
import { renderNewItemView } from "./item_view_new.js";
import {
  LEGACY_ITEM_FIELDS,
  renderLegacyItemDetail,
  renderLegacyItems,
} from "./item_view_legacy.js";
import { actionLink } from "./item_view_primitives.js";

function detailProject(scope, projects) {
  if (Array.isArray(scope)) return scope[0] || null;
  if (scope === "all") return projects[0] ? String(projects[0].id) : null;
  return scope;
}

function claimLabel(row) {
  const claim = row.claimed_by;
  return claim ? (claim.actor_label || claim.session_id || "") : "";
}

function itemTable(documentNode, rows, rowHref) {
  if (!rows.length) {
    return el(documentNode, "p", "empty", "No items match this view.");
  }
  const table = el(documentNode, "table", "items item-roster");
  const head = el(documentNode, "tr");
  for (const label of [
    "ID", "Title", "Workflow", "Status", "Owner", "Claimed by",
  ]) {
    head.appendChild(el(documentNode, "th", null, label));
  }
  table.appendChild(head);
  for (const row of rows) {
    const tr = el(documentNode, "tr");
    const refCell = el(documentNode, "td", "mono");
    const link = el(documentNode, "a", "row-link", row.public_ref);
    link.href = rowHref(row);
    refCell.appendChild(link);
    tr.appendChild(refCell);
    tr.appendChild(el(documentNode, "td", "item-roster-title", row.title));
    const workflowCell = el(documentNode, "td");
    const workflow = el(
      documentNode,
      "span",
      `item-workflow ${String(row.workflow_id || "").toLowerCase()}`,
      row.workflow_id,
    );
    workflow.setAttribute("data-workflow", row.workflow_id);
    workflowCell.appendChild(workflow);
    tr.appendChild(workflowCell);
    const statusCell = el(documentNode, "td");
    const status = statePill(documentNode, row.status);
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
    table.appendChild(tr);
  }
  return table;
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
    const values = [...new Set(rows.map((row) => row[key]).filter(Boolean))]
      .sort();
    for (const value of values) {
      const option = el(documentNode, "option", null, value);
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

export function renderItemsView(context, main, scope) {
  const documentNode = context.document;
  const projects = context.projects();
  const panel = section(documentNode, "Items", { showRaw: false });
  const toolbar = el(documentNode, "div", "item-roster-toolbar");
  const note = el(
    documentNode,
    "p",
    "item-roster-note",
    "Every durable piece of project work, across Issue, Epic, Blitz, and Dash.",
  );
  const actions = el(documentNode, "div", "item-roster-actions");
  const filterButton = el(documentNode, "button", "item-button", "Filter ▾");
  filterButton.type = "button";
  const projectId = detailProject(scope, projects);
  actions.appendChild(filterButton);
  actions.appendChild(actionLink(
    documentNode,
    "New item",
    buildUniverseRoute("items", projectId, "new"),
    true,
  ));
  toolbar.appendChild(note);
  toolbar.appendChild(actions);
  const filterHost = el(documentNode, "div");
  main.replaceChildren(toolbar, filterHost, panel);
  const filterState = {
    open: false,
    query: "",
    workflow: "",
    status: "",
  };
  filterButton.addEventListener("click", () => {
    filterState.open = !filterState.open;
    filterHost.hidden = !filterState.open;
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
        ));
        filterHost.replaceChildren(filterControls(
          documentNode, rows, filterState, renderRows,
        ));
        filterHost.hidden = !filterState.open;
      };
      renderRows();
    });
  };
  const renderLegacy = (callResults) => {
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
      renderLegacyItems(body, rows, scope, projects);
    });
  };
  settledScopedCalls(context, calls).then(async ({ callResults, failed }) => {
    if (!context.isMounted()) return;
    if (!failed) {
      renderPrototype(callResults);
      return;
    }
    const legacyCalls = buckets.map((bucket) => ({
      functionId: "items.list.run",
      payload: {
        fields: LEGACY_ITEM_FIELDS,
        ...(bucket === null ? {} : { project: bucket }),
      },
    }));
    const legacy = await settledScopedCalls(context, legacyCalls);
    if (!context.isMounted()) return;
    if (!legacy.failed) {
      renderLegacy(legacy.callResults);
      return;
    }
    panel.renderEnvelope(failed, (body) => renderError(body, failed));
  });
}

export function renderItemDetailView(
  context,
  main,
  projectId,
  itemRef,
) {
  if (String(itemRef).toLowerCase() === "new") {
    renderNewItemView(context, main, projectId);
    return;
  }
  const loading = section(
    context.document, String(itemRef), { showRaw: false },
  );
  main.replaceChildren(loading);
  const target = {
    kind: "item",
    item_ref: String(itemRef),
    project_id: String(projectId),
  };
  (async () => {
    let callResult;
    try {
      callResult = await callFunction(
        context.client,
        "items.detail.get",
        {},
        target,
      );
    } catch (error) {
      callResult = {
        status: 0,
        envelope: { success: false, error: { message: String(error) } },
      };
    }
    if (!context.isMounted()) return;
    if (callResult.status === 200 && callResult.envelope.success) {
      const item = (callResult.envelope.result || {}).item;
      if (String(item.workflow_id || "").toLowerCase() === "blitz") {
        renderBlitzItemDetail(context, main, item);
      } else {
        renderWorkflowItemDetail(context, main, item);
      }
      return;
    }
    let legacy;
    try {
      legacy = await callFunction(
        context.client,
        "items.get.run",
        {},
        target,
      );
    } catch (error) {
      legacy = {
        status: 0,
        envelope: { success: false, error: { message: String(error) } },
      };
    }
    if (!context.isMounted()) return;
    if (legacy.status === 200 && legacy.envelope.success) {
      renderLegacyItemDetail(
        context, main, projectId, itemRef, legacy,
      );
      return;
    }
    loading.renderEnvelope(callResult, (body) => renderError(body, callResult));
  })();
}
