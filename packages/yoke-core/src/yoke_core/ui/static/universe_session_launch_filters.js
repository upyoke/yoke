import { el } from "./universe_view_support.js";

// Each criterion is applied by the server before selection and counting, so
// the options offered here are only ever the values already on screen plus
// whatever is currently chosen.
const FILTER_FIELDS = [
  ["state", "State", "Any state", (row) => [row.state]],
  [
    "surface", "Surface", "Any surface",
    (row) => [row.requested_surface, row.selected_surface],
  ],
  [
    "machine", "Machine", "Any machine",
    (row) => [row.assigned_machine_id, row.requested_machine_id],
  ],
];

function option(documentNode, value, label) {
  const node = el(documentNode, "option", null, label);
  node.value = value;
  return node;
}

export function launchFilters(documentNode, onChange) {
  const host = el(documentNode, "div", "session-roster-filters");
  host.setAttribute("role", "search");
  host.setAttribute("aria-label", "Filter session launches");
  const selects = new Map();
  for (const [key, label] of FILTER_FIELDS) {
    const wrapper = el(documentNode, "label", "session-roster-filter");
    wrapper.appendChild(el(documentNode, "span", "session-filter-label", label));
    const select = el(documentNode, "select", "session-filter-control");
    select.setAttribute("data-launch-filter", key);
    select.addEventListener("change", onChange);
    wrapper.appendChild(select);
    host.appendChild(wrapper);
    selects.set(key, select);
  }
  return {
    host,
    offer(rows) {
      for (const [key, , empty, read] of FILTER_FIELDS) {
        const select = selects.get(key);
        const chosen = String(select.value || "");
        // The chosen value stays offered even when no loaded row carries it,
        // so a filter that matches nothing cannot silently clear itself.
        const values = [...new Set(
          [chosen, ...rows.flatMap(read)].filter(Boolean).map(String),
        )].sort();
        select.replaceChildren(
          option(documentNode, "", empty),
          ...values.map((value) => option(documentNode, value, value)),
        );
        select.value = chosen;
      }
    },
    criteria() {
      const chosen = {};
      for (const [key, select] of selects) {
        const value = String(select.value || "");
        if (value) chosen[key] = value;
      }
      return chosen;
    },
  };
}
