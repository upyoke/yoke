import { el, statePill } from "./universe_view_support.js";

function flowName(row) {
  return row.name || row.id || "Unnamed flow";
}
function flowStatus(row) {
  return String(row.status || "unknown").toLowerCase();
}

function stagesFor(row) {
  return Array.isArray(row.stage_names) ? row.stage_names : [];
}
function searchableText(row) {
  return [
    row.name,
    row.id,
    row.project,
    row.status,
    row.target_tier,
    row.target_environment,
    row.on_failure,
    ...stagesFor(row),
  ].filter(Boolean).join(" ").toLowerCase();
}
function sortedRows(rows) {
  return [...rows].sort((left, right) => {
    const projectOrder = String(left.project || "").localeCompare(
      String(right.project || ""),
    );
    if (projectOrder) return projectOrder;
    const leftDisabled = flowStatus(left) === "disabled";
    const rightDisabled = flowStatus(right) === "disabled";
    if (leftDisabled !== rightDisabled) return leftDisabled ? 1 : -1;
    return flowName(left).localeCompare(flowName(right));
  });
}
function stageShape(documentNode, row) {
  const stages = stagesFor(row);
  const shape = el(documentNode, "span", "delivery-flow-card-shape");
  shape.setAttribute("role", "img");
  shape.setAttribute(
    "aria-label",
    stages.length
      ? `${stages.length} stages: ${stages.join(", ")}`
      : "No stages published",
  );
  if (!stages.length) {
    shape.appendChild(el(documentNode, "i", "is-empty"));
    return shape;
  }
  for (const stage of stages) shape.appendChild(el(documentNode, "i"));
  return shape;
}
function metadataFact(documentNode, label, value) {
  const fact = el(documentNode, "div", "delivery-flow-fact");
  fact.appendChild(el(documentNode, "dt", null, label));
  fact.appendChild(el(documentNode, "dd", null, value || "Not set"));
  return fact;
}
function renderPipeline(documentNode, row) {
  const stages = stagesFor(row);
  const region = el(documentNode, "section", "delivery-flow-pipeline-region");
  region.appendChild(el(documentNode, "h4", null, "Pipeline"));
  if (!stages.length) {
    region.appendChild(el(
      documentNode,
      "p",
      "delivery-flow-no-stages",
      "No stages are published for this flow.",
    ));
    return region;
  }
  const pipeline = el(documentNode, "ol", "delivery-flow-pipeline");
  pipeline.setAttribute("aria-label", `Flow stages: ${stages.join(", ")}`);
  for (const [index, stage] of stages.entries()) {
    const item = el(documentNode, "li", "delivery-flow-stage");
    item.appendChild(el(
      documentNode,
      "span",
      "delivery-flow-stage-index",
      String(index + 1).padStart(2, "0"),
    ));
    item.appendChild(el(
      documentNode,
      "span",
      "delivery-flow-stage-name",
      stage,
    ));
    pipeline.appendChild(item);
  }
  region.appendChild(pipeline);
  return region;
}
function renderDetail(documentNode, detail, row) {
  detail.replaceChildren();
  if (!row) {
    detail.classList.add("is-empty");
    detail.removeAttribute("aria-labelledby");
    detail.appendChild(el(
      documentNode,
      "p",
      "delivery-flow-detail-empty",
      "Choose a visible flow to inspect its pipeline.",
    ));
    return;
  }
  detail.classList.remove("is-empty");
  const header = el(documentNode, "header", "delivery-flow-detail-header");
  header.appendChild(el(
    documentNode, "p", "delivery-flow-eyebrow", "Selected flow",
  ));
  const titleRow = el(documentNode, "div", "delivery-flow-detail-title");
  const heading = el(documentNode, "h3", null, flowName(row));
  heading.setAttribute("id", "delivery-flow-detail-heading");
  titleRow.appendChild(heading);
  const pill = statePill(documentNode, flowStatus(row), flowStatus(row));
  if (pill) titleRow.appendChild(pill);
  header.appendChild(titleRow);
  header.appendChild(el(
    documentNode,
    "code",
    "delivery-flow-id",
    row.id || "identity unavailable",
  ));
  detail.appendChild(header);
  detail.setAttribute("aria-labelledby", "delivery-flow-detail-heading");

  const facts = el(documentNode, "dl", "delivery-flow-facts");
  facts.appendChild(metadataFact(documentNode, "Project", row.project));
  facts.appendChild(metadataFact(
    documentNode, "Environment", row.target_environment || "Ephemeral",
  ));
  facts.appendChild(metadataFact(documentNode, "Target tier", row.target_tier));
  facts.appendChild(metadataFact(
    documentNode, "On failure", row.on_failure || "halt",
  ));
  facts.appendChild(metadataFact(
    documentNode,
    "Stage count",
    `${stagesFor(row).length} stage${stagesFor(row).length === 1 ? "" : "s"}`,
  ));
  detail.appendChild(facts);
  detail.appendChild(renderPipeline(documentNode, row));
}
function flowCard(documentNode, row, selected, index) {
  const card = el(documentNode, "button", "delivery-flow-card");
  card.type = "button";
  card.setAttribute("role", "option");
  card.setAttribute("id", `delivery-flow-option-${index}`);
  card.setAttribute("aria-selected", String(selected));
  card.setAttribute("aria-controls", "delivery-flow-detail");
  card.setAttribute("data-status", flowStatus(row));
  card.tabIndex = selected ? 0 : -1;
  card.classList.toggle("selected", selected);

  const header = el(documentNode, "span", "delivery-flow-card-header");
  header.appendChild(el(
    documentNode, "strong", "delivery-flow-card-name", flowName(row),
  ));
  const pill = statePill(documentNode, flowStatus(row), flowStatus(row));
  if (pill) header.appendChild(pill);
  card.appendChild(header);
  const meta = el(documentNode, "span", "delivery-flow-card-meta");
  meta.appendChild(el(
    documentNode, "span", "delivery-flow-card-project", row.project || "Unknown project",
  ));
  meta.appendChild(el(
    documentNode,
    "span",
    null,
    `${stagesFor(row).length} stage${stagesFor(row).length === 1 ? "" : "s"}`,
  ));
  card.appendChild(meta);
  card.appendChild(stageShape(documentNode, row));
  return card;
}
function zeroState(documentNode, title, copy, className = "") {
  const empty = el(
    documentNode,
    "div",
    `delivery-flow-zero ${className}`.trim(),
  );
  empty.setAttribute("role", "status");
  empty.appendChild(el(documentNode, "span", "delivery-flow-zero-mark", "↗"));
  empty.appendChild(el(documentNode, "h3", null, title));
  empty.appendChild(el(documentNode, "p", null, copy));
  return empty;
}
export function renderDeliveryFlowExplorer(body, panel, sourceRows) {
  const documentNode = body.ownerDocument;
  const rows = sortedRows(sourceRows);
  panel.classList.add("delivery-flow-panel");
  if (!rows.length) {
    panel.setCount(0);
    body.appendChild(zeroState(
      documentNode,
      "No deployment flows yet",
      "Definitions published for this project scope will appear here.",
      "delivery-flow-empty-scope",
    ));
    return;
  }

  const disabledCount = rows.filter(
    (row) => flowStatus(row) === "disabled",
  ).length;
  const state = {
    query: "",
    showHistory: false,
    selected: rows.find((row) => flowStatus(row) !== "disabled") || null,
  };
  const explorer = el(documentNode, "div", "delivery-flow-explorer");
  const toolbar = el(documentNode, "div", "delivery-flow-toolbar");
  const searchLabel = el(documentNode, "label", "delivery-flow-search");
  searchLabel.appendChild(el(documentNode, "span", null, "Search flows"));
  const search = el(documentNode, "input");
  search.type = "search";
  search.placeholder = "Name, project, stage, target…";
  search.setAttribute("aria-controls", "delivery-flow-list");
  searchLabel.appendChild(search);
  toolbar.appendChild(searchLabel);
  const history = el(documentNode, "button", "delivery-flow-history-toggle");
  history.type = "button";
  history.hidden = disabledCount === 0;
  toolbar.appendChild(history);
  const summary = el(documentNode, "p", "delivery-flow-result-summary");
  summary.setAttribute("aria-live", "polite");
  toolbar.appendChild(summary);
  explorer.appendChild(toolbar);

  const workspace = el(documentNode, "div", "delivery-flow-workspace");
  const browser = el(documentNode, "aside", "delivery-flow-browser");
  browser.setAttribute("aria-label", "Deployment flow catalog");
  const list = el(documentNode, "div", "delivery-flow-list");
  list.setAttribute("id", "delivery-flow-list");
  list.setAttribute("role", "listbox");
  list.setAttribute("aria-label", "Deployment flows");
  browser.appendChild(list);
  const detail = el(documentNode, "article", "delivery-flow-detail");
  detail.setAttribute("id", "delivery-flow-detail");
  workspace.appendChild(browser);
  workspace.appendChild(detail);
  explorer.appendChild(workspace);
  body.appendChild(explorer);

  let cardByRow = new Map();
  const visibleRows = () => rows.filter((row) => {
    if (!state.showHistory && flowStatus(row) === "disabled") return false;
    return !state.query || searchableText(row).includes(state.query);
  });

  const paint = () => {
    const visible = visibleRows();
    if (!visible.includes(state.selected)) state.selected = visible[0] || null;
    panel.setCount(visible.length);
    history.textContent = state.showHistory
      ? "Hide history"
      : `Show history (${disabledCount})`;
    history.setAttribute("aria-pressed", String(state.showHistory));
    summary.textContent = `${visible.length} flow${visible.length === 1 ? "" : "s"} shown` +
      (!state.showHistory && disabledCount
        ? ` · ${disabledCount} historical hidden`
        : "");
    list.replaceChildren();
    cardByRow = new Map();
    if (!visible.length) {
      const historyHint = !state.showHistory && disabledCount
        ? " Historical definitions remain hidden."
        : "";
      const empty = zeroState(
        documentNode,
        state.query ? "No matching flows" : "No active flows",
        state.query
          ? `Nothing matches “${search.value}”.${historyHint}`
          : `${disabledCount} historical definition${disabledCount === 1 ? " is" : "s are"} hidden.`,
        "delivery-flow-no-results",
      );
      if (state.query) {
        const clear = el(documentNode, "button", "delivery-flow-clear", "Clear search");
        clear.type = "button";
        clear.addEventListener("click", () => {
          search.value = "";
          state.query = "";
          paint();
          search.focus();
        });
        empty.appendChild(clear);
      }
      list.appendChild(empty);
      renderDetail(documentNode, detail, null);
      return;
    }

    const groups = new Map();
    for (const row of visible) {
      const project = row.project || "Unknown project";
      if (!groups.has(project)) groups.set(project, []);
      groups.get(project).push(row);
    }
    let optionIndex = 0;
    for (const [project, projectRows] of groups) {
      const group = el(documentNode, "section", "delivery-flow-project-group");
      group.setAttribute("role", "group");
      group.setAttribute("aria-label", project);
      group.appendChild(el(documentNode, "h3", null, project));
      for (const row of projectRows) {
        const card = flowCard(
          documentNode, row, row === state.selected, optionIndex,
        );
        optionIndex += 1;
        cardByRow.set(row, card);
        card.addEventListener("click", () => {
          state.selected = row;
          paint();
          cardByRow.get(row)?.focus();
        });
        card.addEventListener("keydown", (event) => {
          const index = visible.indexOf(row);
          let next = null;
          if (["ArrowDown", "ArrowRight"].includes(event.key)) {
            next = (index + 1) % visible.length;
          } else if (["ArrowUp", "ArrowLeft"].includes(event.key)) {
            next = (index - 1 + visible.length) % visible.length;
          } else if (event.key === "Home") next = 0;
          else if (event.key === "End") next = visible.length - 1;
          if (next === null) return;
          event.preventDefault();
          state.selected = visible[next];
          paint();
          cardByRow.get(state.selected)?.focus();
        });
        group.appendChild(card);
      }
      list.appendChild(group);
    }
    renderDetail(documentNode, detail, state.selected);
  };

  search.addEventListener("input", () => {
    state.query = String(search.value || "").trim().toLowerCase();
    paint();
  });
  history.addEventListener("click", () => {
    state.showHistory = !state.showHistory;
    paint();
  });
  paint();
}
