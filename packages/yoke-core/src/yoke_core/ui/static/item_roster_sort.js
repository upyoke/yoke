import { el } from "./universe_view_support.js";

const KEYS = {
  ID: "id", project: "project", Title: "title", Workflow: "workflow",
  Status: "status", Owner: "owner", "Claimed by": "claimed_by", "Last updated": "updated_at",
};

export function normalizeItemSort(sort) {
  return Object.values(KEYS).includes(sort?.column) && ["asc", "desc"].includes(sort?.direction)
    ? { column: sort.column, direction: sort.direction }
    : { column: "updated_at", direction: "desc" };
}

export function sortHeader(documentNode, label, sort, onSort, explicitColumn) {
  const column = explicitColumn || KEYS[label];
  const active = column === sort.column;
  const th = el(documentNode, "th");
  th.setAttribute("aria-sort", active ? sort.direction === "asc" ? "ascending" : "descending" : "none");
  const button = el(documentNode, "button", "item-sort-button", `${label}${active ? sort.direction === "asc" ? " ↑" : " ↓" : ""}`);
  button.type = "button";
  button.setAttribute("data-sort-column", column);
  button.setAttribute("aria-label", `Sort by ${label}, ${active && sort.direction === "asc" ? "descending" : "ascending"}`);
  button.addEventListener("click", () => onSort(column));
  th.appendChild(button);
  return th;
}
