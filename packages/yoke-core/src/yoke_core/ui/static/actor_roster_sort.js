// Actors roster ordering and grant wording. The roster is one full read, so
// ordering happens here; the chosen sort is saved under the "actors" screen.

export const ACTOR_SORT_COLUMNS = {
  Actor: "name", State: "status", "Org role": "org_role",
  "Project access": "project_access", "Member email": "email", "API keys": "api_keys",
};

export function normalizeActorSort(sort) {
  return Object.values(ACTOR_SORT_COLUMNS).includes(sort?.column) && ["asc", "desc"].includes(sort?.direction)
    ? { column: sort.column, direction: sort.direction }
    : { column: "name", direction: "asc" };
}

// Project grants read "project (role)" so a role never looks like a project.
export function projectAccess(actor) {
  const grants = (actor.roles?.projects || []).map((row) => `${row.project} (${row.role})`);
  if ((actor.roles?.org || []).some((row) => row.role === "admin")) grants.unshift("all projects");
  return grants.join(", ");
}

const SORT_VALUES = {
  name: (actor) => actor.name || "",
  status: (actor) => actor.status || "active",
  org_role: (actor) => (actor.roles?.org || []).map((row) => row.role).join(", "),
  project_access: projectAccess,
  email: (actor) => actor.identity?.email || "",
  api_keys: (actor) => actor.tokens?.length || 0,
};

export function sortActors(rows, sort) {
  const value = SORT_VALUES[sort.column];
  const sign = sort.direction === "desc" ? -1 : 1;
  return [...rows].sort((left, right) => {
    const a = value(left);
    const b = value(right);
    const order = typeof a === "number"
      ? a - b : a.localeCompare(b, undefined, { sensitivity: "base", numeric: true });
    return sign * order || left.id - right.id;
  });
}
