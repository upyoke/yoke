import { callFunction } from "./universe_view_support.js";
import { SEARCH_DEBOUNCE_MS } from "./universe_shell_controls.js";

export const RUNS_PAGE_SIZE = 50;
const TERMINAL_STATUSES = new Set(["cancelled", "failed", "succeeded"]);

function scopeProjects(scope) {
  if (scope === "all" || scope === null || scope === undefined) return null;
  const projects = (Array.isArray(scope) ? scope : [scope])
    .map((value) => String(value))
    .filter(Boolean);
  return projects.length ? projects : null;
}

function requestPayload(scope, criteria, cursor) {
  const scoped = scopeProjects(scope);
  const projects = criteria.project ? [criteria.project] : scoped;
  const search = criteria.query.trim();
  return {
    page: {
      page_size: RUNS_PAGE_SIZE,
      ...(projects ? { projects } : {}),
      ...(search ? { search } : {}),
      ...(criteria.status ? { status: criteria.status } : {}),
      ...(criteria.environment ? { environment: criteria.environment } : {}),
      ...(criteria.flow ? { flow: criteria.flow } : {}),
      ...(cursor ? { cursor } : {}),
    },
  };
}

function failed(result) {
  return result?.status !== 200 || result?.envelope?.success !== true;
}

function mergeById(existing, added) {
  const rows = new Map(existing.map((row) => [String(row.id), row]));
  for (const row of added) rows.set(String(row.id), row);
  return [...rows.values()];
}

export function createDeploymentRunsLoader({ context, scope, onChange }) {
  const criteria = {
    query: "", project: "", status: "", environment: "", flow: "",
  };
  let generation = 0;
  let unfinishedRows = [];
  let completedRows = [];
  let unfinishedCount = 0;
  let completedMatchCount = 0;
  let completedLoadedCount = 0;
  let nextCursor = null;
  let filters = { projects: [], statuses: [], environments: [], flows: [] };
  let failure = null;
  let loading = false;
  let searchTimer = null;

  const state = () => ({
    criteria: { ...criteria },
    rows: [...unfinishedRows, ...completedRows],
    unfinishedCount,
    completedMatchCount,
    completedLoadedCount,
    filters,
    failure,
    loading,
    hasMore: nextCursor !== null,
  });
  const publish = () => {
    if (context.isMounted() && typeof onChange === "function") onChange(state());
  };

  const request = async ({ append }) => {
    generation += 1;
    const token = generation;
    if (!append) {
      unfinishedRows = [];
      completedRows = [];
      unfinishedCount = 0;
      completedMatchCount = 0;
      completedLoadedCount = 0;
      nextCursor = null;
    }
    loading = true;
    failure = null;
    publish();
    let result;
    try {
      result = await callFunction(
        context.client,
        "deployment_runs.list",
        requestPayload(scope, criteria, append ? nextCursor : null),
      );
    } catch (error) {
      result = {
        status: 0,
        envelope: { success: false, error: { message: String(error) } },
      };
    }
    if (token !== generation || !context.isMounted()) return false;
    loading = false;
    if (failed(result)) {
      failure = result;
      publish();
      return false;
    }
    const payload = result.envelope.result || {};
    const rows = payload.rows || [];
    if (append) {
      unfinishedRows = rows.filter((row) => !TERMINAL_STATUSES.has(row.status));
      completedRows = mergeById(
        completedRows,
        rows.filter((row) => TERMINAL_STATUSES.has(row.status)),
      );
    } else {
      unfinishedRows = rows.filter((row) => !TERMINAL_STATUSES.has(row.status));
      completedRows = rows.filter((row) => TERMINAL_STATUSES.has(row.status));
    }
    unfinishedCount = Number(payload.unfinished_count) || 0;
    completedMatchCount = Number(payload.completed_match_count) || 0;
    completedLoadedCount = Number(payload.completed_loaded_count) || 0;
    nextCursor = payload.next_cursor || null;
    if (payload.filters) filters = payload.filters;
    failure = null;
    publish();
    return true;
  };

  const reload = () => request({ append: false });
  return {
    state,
    start: reload,
    loadMore: () => (nextCursor ? request({ append: true }) : Promise.resolve(false)),
    setFilter(key, value) {
      criteria[key] = value;
      return reload();
    },
    setQuery(value) {
      criteria.query = value;
      generation += 1;
      if (searchTimer !== null) clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        searchTimer = null;
        reload();
      }, SEARCH_DEBOUNCE_MS);
    },
    destroy() {
      generation += 1;
      if (searchTimer !== null) clearTimeout(searchTimer);
    },
  };
}
