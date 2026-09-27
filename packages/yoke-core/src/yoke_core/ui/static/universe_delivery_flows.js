// Deployments → Flows: a searchable list of flow definitions grouped by
// project beside the selected flow. On a narrow content pane the list comes
// first and a chosen flow opens alone, with "‹ All flows" to return.
import { el, statePill } from "./universe_view_support.js";
import {
  flowName,
  flowStatus,
  renderDeliveryFlowDetail,
} from "./universe_delivery_flow_detail.js";

function stageNames(row) {
  return (Array.isArray(row.stages) ? row.stages : []).map((stage) => stage.name);
}
function searchableText(row) {
  return [
    row.name,
    row.id,
    row.project,
    row.target_environment,
    row.target_tier,
    ...stageNames(row),
  ].filter(Boolean).join(" ").toLowerCase();
}
function isActive(row) {
  return flowStatus(row) === "active";
}
// Scoped projects first, then the rest by name; within a project, active
// flows before disabled ones, each by name.
function sortedRows(rows, leadingProjects = []) {
  const lead = (row) => {
    const at = leadingProjects.indexOf(String(row.project || ""));
    return at === -1 ? leadingProjects.length : at;
  };
  return [...rows].sort((left, right) => {
    const leadOrder = lead(left) - lead(right);
    if (leadOrder) return leadOrder;
    const projectOrder = String(left.project || "").localeCompare(String(right.project || ""));
    if (projectOrder) return projectOrder;
    if (isActive(left) !== isActive(right)) return isActive(left) ? -1 : 1;
    return flowName(left).localeCompare(flowName(right));
  });
}

function flowRowMeta(row) {
  const count = stageNames(row).length;
  return [
    row.target_environment,
    `${count} stage${count === 1 ? "" : "s"}`,
  ].filter(Boolean).join(" · ");
}

function flowRowButton(documentNode, row, selected) {
  const button = el(documentNode, "button", "delivery-flow-row");
  button.type = "button";
  button.setAttribute("data-flow-id", String(row.id));
  button.setAttribute("aria-current", String(selected));
  button.classList.toggle("is-selected", selected);
  button.appendChild(el(documentNode, "span", "delivery-flow-row-name", flowName(row)));
  // Active is the ordinary case; only an exception earns a pill.
  if (!isActive(row)) {
    const pill = statePill(documentNode, flowStatus(row), flowStatus(row));
    if (pill) button.appendChild(pill);
  }
  button.appendChild(el(documentNode, "span", "delivery-flow-row-meta", flowRowMeta(row)));
  return button;
}

export function renderDeliveryFlowExplorer(body, panel, sourceRows, selectedId = null, options = {}) {
  const documentNode = body.ownerDocument;
  const rows = sortedRows(sourceRows, options.leadingProjects || []);
  panel.classList.add("delivery-flow-panel");
  if (!rows.length) {
    panel.setCount(0);
    body.appendChild(el(
      documentNode,
      "p",
      "delivery-flow-empty",
      "No deployment flows yet. Flows are created with `yoke deployment-flows create`.",
    ));
    return;
  }
  const disabledCount = rows.filter((row) => !isActive(row)).length;
  // A route naming a flow opens on it, including a disabled one — a link to
  // a retired definition lands on that definition.
  const routed = selectedId
    ? rows.find((row) => String(row.id) === String(selectedId)) || null
    : null;
  const state = {
    query: "",
    showDisabled: Boolean(routed && !isActive(routed)),
    selected: routed || rows.find(isActive) || rows[0],
    open: Boolean(routed),
  };

  const page = el(documentNode, "div", "delivery-flow-page");
  const list = el(documentNode, "aside", "delivery-flow-list");
  list.setAttribute("aria-label", "Deployment flows");
  const tools = el(documentNode, "div", "delivery-flow-tools");
  const search = el(documentNode, "input", "delivery-flow-search");
  search.type = "search";
  search.placeholder = "Search flows, stages, environments";
  search.setAttribute("aria-label", "Search flows");
  const toggle = el(documentNode, "label", "delivery-flow-show-disabled");
  const box = el(documentNode, "input");
  box.type = "checkbox";
  box.checked = state.showDisabled;
  toggle.appendChild(box);
  toggle.appendChild(documentNode.createTextNode(` Show disabled (${disabledCount})`));
  tools.appendChild(search);
  tools.appendChild(toggle);
  const count = el(documentNode, "p", "delivery-flow-count");
  count.setAttribute("aria-live", "polite");
  const groups = el(documentNode, "div", "delivery-flow-groups");
  for (const part of [tools, count, groups]) list.appendChild(part);
  const detail = el(documentNode, "article", "delivery-flow-detail");
  detail.setAttribute("id", "delivery-flow-detail");
  page.appendChild(list);
  page.appendChild(detail);
  body.appendChild(page);

  const visibleRows = () => rows.filter((row) => (
    (state.showDisabled || isActive(row))
    && (!state.query || searchableText(row).includes(state.query))
  ));

  const select = (row) => {
    state.selected = row;
    state.open = true;
    if (!isActive(row) && !state.showDisabled) {
      state.showDisabled = true;
      box.checked = true;
    }
    paint();
    page.scrollIntoView?.({ block: "start" });
  };

  const paintList = (visible) => {
    panel.setCount(visible.length);
    count.textContent = `${visible.length} flow${visible.length === 1 ? "" : "s"}`;
    groups.replaceChildren();
    if (!visible.length) {
      groups.appendChild(el(documentNode, "p", "delivery-flow-empty", "No flows match."));
      return;
    }
    const byProject = new Map();
    for (const row of visible) {
      const project = row.project || "Unknown project";
      if (!byProject.has(project)) byProject.set(project, []);
      byProject.get(project).push(row);
    }
    for (const [project, projectRows] of byProject) {
      const group = el(documentNode, "section", "delivery-flow-group");
      group.appendChild(el(documentNode, "h3", null, project));
      const items = el(documentNode, "ul");
      for (const row of projectRows) {
        const button = flowRowButton(documentNode, row, row === state.selected);
        button.addEventListener("click", () => select(row));
        const item = el(documentNode, "li");
        item.appendChild(button);
        items.appendChild(item);
      }
      group.appendChild(items);
      groups.appendChild(group);
    }
  };

  const paint = () => {
    const visible = visibleRows();
    if (!visible.includes(state.selected)) state.selected = visible[0] || null;
    page.classList.toggle("is-detail-open", state.open && Boolean(state.selected));
    paintList(visible);
    renderDeliveryFlowDetail(documentNode, detail, state.selected, {
      flows: rows,
      actorNames: options.actorNames || {},
      flowHref: options.flowHref,
      runHref: options.runHref,
      loadRecentRuns: options.loadRecentRuns,
      onSelect: select,
      onBack: () => {
        state.open = false;
        page.classList.remove("is-detail-open");
      },
    });
  };

  search.addEventListener("input", () => {
    state.query = String(search.value || "").trim().toLowerCase();
    paint();
  });
  box.addEventListener("change", () => {
    state.showDisabled = box.checked;
    paint();
  });
  paint();
}
