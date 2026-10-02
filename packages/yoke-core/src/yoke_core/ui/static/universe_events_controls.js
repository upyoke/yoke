import { SEVERITY_CHOICES, SINCE_CHOICES } from "./universe_events_history_loader.js";
import { el } from "./universe_view_support.js";

let controlSequence = 0;
function field(documentNode, label, control) {
  const wrap = el(documentNode, "label", "event-criterion");
  wrap.appendChild(el(documentNode, "span", "event-criterion-label", label));
  wrap.appendChild(control);
  return wrap;
}
function selectField(documentNode, label, choices, onPick) {
  const select = el(documentNode, "select");
  for (const [value, text] of choices) {
    const option = el(documentNode, "option", null, text);
    option.value = value;
    select.appendChild(option);
  }
  select.addEventListener("change", () => onPick(select.value));
  return field(documentNode, label, select);
}

export function eventsControls(documentNode, loader, onSearch) {
  const host = el(documentNode, "div", "event-controls");
  const primary = el(documentNode, "div", "event-criteria-bar");
  const search = el(documentNode, "input");
  search.type = "search";
  search.placeholder = "Search event, target or context";
  search.addEventListener("input", onSearch);
  primary.appendChild(field(documentNode, "Search loaded entries", search));
  const clear = el(documentNode, "button", "item-button", "Clear search");
  clear.type = "button";
  clear.addEventListener("click", () => { search.value = ""; onSearch(); search.focus(); });
  primary.appendChild(clear);
  primary.appendChild(selectField(documentNode, "Severity", [
    ["", "Any severity"], ...SEVERITY_CHOICES.map((value) => [value, `${value} and above`]),
  ], (value) => loader.setCriterion("min_severity", value)));
  primary.appendChild(selectField(documentNode, "Since", SINCE_CHOICES,
    (value) => loader.setCriterion("since", value)));
  const advanced = el(documentNode, "details", "event-advanced");
  advanced.appendChild(el(documentNode, "summary", null, "Advanced filters · all history"));
  const exact = el(documentNode, "div", "event-criteria-bar");
  const suggestions = [];
  for (const [key, label, placeholder] of [
    ["event_name", "Event", "Exact event name"],
    ["source_type", "Source", "Exact source type"],
  ]) {
    const control = el(documentNode, "input");
    control.type = "search";
    control.placeholder = placeholder;
    const list = el(documentNode, "datalist");
    list.id = `event-suggestions-${++controlSequence}`;
    control.setAttribute("list", list.id);
    control.addEventListener("input", () => loader.setTypedCriterion(key, control.value));
    exact.appendChild(field(documentNode, label, control));
    exact.appendChild(list);
    suggestions.push({ key, list, values: new Set() });
  }
  advanced.appendChild(exact);
  const status = el(documentNode, "p", "secondary-muted event-search-status");
  status.setAttribute("role", "status");
  status.textContent = "Search checks loaded entries. Load more to include older events.";
  for (const node of [primary, advanced, status]) host.appendChild(node);
  return {
    host,
    matches(row) {
      const query = search.value.trim().toLowerCase();
      return !query || [row.event_name, row.context_label, row.target_label,
        row.source_label, row.source_type, row.project, row.category, row.severity]
        .join(" ").toLowerCase().includes(query);
    },
    report(visible, total) {
      clear.disabled = !search.value;
      status.textContent = `${visible} of ${total} loaded entries shown. Search checks loaded entries; load more to include older events.`;
    },
    setRows(rows) {
      for (const { key, list, values } of suggestions) {
        for (const row of rows) if (row[key]) values.add(String(row[key]));
        list.replaceChildren();
        for (const value of [...values].sort()) {
          const option = el(documentNode, "option");
          option.value = value;
          list.appendChild(option);
        }
      }
    },
  };
}
