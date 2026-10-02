import { el } from "./universe_view_support.js";

const PAGE_SIZE = 25;

function localDay(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0")].join("-");
}

// Filtering and paging apply to the bounded history the existing read serves.
// The bound stays visible so an empty filter never promises older history.
export function activityHistory(context, rows, renderRows) {
  const documentNode = context.document;
  const host = el(documentNode, "div", "qa-activity-history");
  const controls = el(documentNode, "div", "qa-history-filters");
  const field = (name, tag, type) => {
    const label = el(documentNode, "label", "qa-history-field");
    label.appendChild(el(documentNode, "span", null, name));
    const control = el(documentNode, tag, "item-filter-control");
    if (type) control.type = type;
    control.setAttribute("aria-label", name);
    label.appendChild(control);
    controls.appendChild(label);
    return control;
  };
  const query = field("Search history", "input", "search");
  const outcome = field("Outcome", "select");
  for (const value of ["", ...new Set(rows.map((row) => row.outcome).filter(Boolean))]) {
    const option = el(documentNode, "option", null, value ? value.replaceAll("_", " ") : "All outcomes");
    option.value = value;
    outcome.appendChild(option);
  }
  const from = field("From (local date)", "input", "date");
  const to = field("Through (local date)", "input", "date");
  const reset = el(documentNode, "button", "item-button", "Clear filters");
  reset.type = "button";
  controls.appendChild(reset);
  const note = el(documentNode, "p", "item-roster-note",
    "Latest 500 cases per project. Filters apply to this loaded history; older cases may not be included.");
  const count = el(documentNode, "p", "item-roster-note qa-history-count");
  count.setAttribute("aria-live", "polite");
  const body = el(documentNode, "div", "qa-history-results");
  const pager = el(documentNode, "div", "qa-history-pager");
  const previous = el(documentNode, "button", "item-button", "Previous");
  const next = el(documentNode, "button", "item-button", "Next");
  for (const button of [previous, next]) {
    button.type = "button";
    pager.appendChild(button);
  }
  for (const child of [controls, note, count, body, pager]) host.appendChild(child);
  let page = 0;
  const paint = () => {
    const search = query.value.trim().toLowerCase();
    const matches = rows.filter((row) => {
      const date = localDay(row.happened_at);
      return (!outcome.value || row.outcome === outcome.value)
        && (!from.value || date >= from.value) && (!to.value || date <= to.value)
        && (!search || [row.plan, row.case_key, row.method_name, row.project, row.verdict_reason]
          .filter(Boolean).join(" ").toLowerCase().includes(search));
    });
    const start = page * PAGE_SIZE;
    const shown = matches.slice(start, start + PAGE_SIZE);
    count.textContent = matches.length
      ? `${start + 1}–${start + shown.length} of ${matches.length} matching cases`
      : "No cases match these filters in the loaded history.";
    body.replaceChildren();
    if (shown.length || !rows.length) renderRows(body, shown);
    previous.disabled = page === 0;
    next.disabled = start + PAGE_SIZE >= matches.length;
    pager.hidden = matches.length <= PAGE_SIZE;
  };
  for (const control of [query, outcome, from, to]) {
    control.addEventListener(control === query ? "input" : "change", () => { page = 0; paint(); });
  }
  reset.addEventListener("click", () => {
    for (const control of [query, outcome, from, to]) control.value = "";
    page = 0;
    paint();
  });
  previous.addEventListener("click", () => { page -= 1; paint(); count.scrollIntoView?.({ block: "nearest" }); });
  next.addEventListener("click", () => { page += 1; paint(); count.scrollIntoView?.({ block: "nearest" }); });
  paint();
  return host;
}
