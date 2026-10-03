export const OUROBOROS_SORT_COLUMNS = {
  Observation: "preview", "Filed at": "timestamp", Category: "category",
  Context: "context", Reviewed: "reviewed_at", project: "project",
};

export function normalizeOuroborosSort(sort) {
  return Object.values(OUROBOROS_SORT_COLUMNS).includes(sort?.column) && ["asc", "desc"].includes(sort?.direction)
    ? { column: sort.column, direction: sort.direction }
    : { column: "timestamp", direction: "desc" };
}
