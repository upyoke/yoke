import { normalizeItemSort } from "./item_roster_sort.js";
import { refreshScreenSort } from "./universe_app_shell_support.js";
import { callFunction } from "./universe_view_support.js";
import { SEARCH_DEBOUNCE_MS } from "./universe_shell_controls.js";

// One page of matches. The roster reads the whole durable item history, so it
// loads a page at a time instead of transferring the history to render it.
export const ROSTER_PAGE_SIZE = 50;

// The scope's project members as the read wants them: one request carrying
// every project, never one request per project. Rows from separate requests
// cannot be ordered against each other, so a fan-out could not honour a
// newest-first page across a multi-project scope at all.
function scopeProjects(scope) {
  if (scope === "all" || scope === null || scope === undefined) return null;
  const members = (Array.isArray(scope) ? scope : [scope])
    .map((value) => String(value))
    .filter((value) => value !== "");
  return members.length ? members : null;
}

function requestPayload(scope, criteria, cursor) {
  const projects = scopeProjects(scope);
  const query = criteria.query.trim();
  return {
    page_size: ROSTER_PAGE_SIZE,
    sort_column: criteria.sort.column, sort_direction: criteria.sort.direction,
    ...(projects ? { projects } : {}),
    ...(query ? { search: query } : {}),
    ...(criteria.workflow ? { workflow: criteria.workflow } : {}),
    ...(criteria.status ? { status: criteria.status } : {}),
    ...(cursor ? { cursor } : {}),
  };
}

function failureFrom(callResult) {
  if (callResult.status !== 200 || !callResult.envelope.success) {
    return callResult;
  }
  return null;
}

/**
 * Owns the Items roster's request criteria, paging state, and freshness.
 *
 * Every criteria change starts a new sequence: loaded rows and the cursor are
 * dropped, and only the newest request may render. A response that arrives
 * after a newer one was issued is discarded rather than allowed to overwrite
 * the criteria the reader has already moved on to.
 *
 * `Load more` extends the current sequence instead of replacing it, so a page
 * that fails leaves the rows already on screen exactly where they are and the
 * control retryable — dropping fetched rows on a transient failure is worse
 * than never having asked.
 */
export function createRosterLoader({ context, scope, onChange }) {
  const preferences = context.screenPreferences;
  const signal = context.signal;
  const active = () => !signal?.aborted && context.isMounted();
  const criteria = { query: "", workflow: "", status: "", sort: normalizeItemSort(preferences?.sortFor("items")) };
  let sortNotice = "";
  let sequence = 0;
  let rows = [];
  let cursor = null;
  let matchCount = null;
  let filters = { workflow_ids: [], statuses: [] };
  let failure = null;
  let loading = false;
  let debounceTimer = null;

  const state = () => ({
    criteria: { ...criteria },
    rows,
    cursor,
    matchCount,
    filters,
    failure,
    loading,
    hasMore: cursor !== null, sortNotice,
  });

  const publish = () => {
    if (typeof onChange === "function") onChange(state());
  };

  const request = async ({ append }) => {
    sequence += 1;
    const token = sequence;
    if (!append) {
      rows = [];
      cursor = null;
      matchCount = null;
    }
    loading = true;
    failure = null;
    publish();
    let callResult;
    try {
      callResult = await callFunction(
        context.client,
        "items.overview.list",
        requestPayload(scope, criteria, append ? cursor : null),
      );
    } catch (fetchError) {
      // No HTTP response at all: status 0 marks it so the panel shows the
      // failure instead of sticking at "loading…".
      callResult = {
        status: 0,
        envelope: { success: false, error: { message: String(fetchError) } },
      };
    }
    // A newer sequence already owns the view. This reply answers criteria the
    // reader has moved past, so it is dropped rather than rendered.
    if (token !== sequence) return;
    if (!active()) return;
    loading = false;
    const failed = failureFrom(callResult);
    if (failed) {
      failure = failed;
      publish();
      return;
    }
    const result = callResult.envelope.result || {};
    rows = append ? [...rows, ...(result.rows || [])] : (result.rows || []);
    cursor = result.next_cursor || null;
    matchCount = typeof result.match_count === "number"
      ? result.match_count
      : null;
    // Choices describe the whole scope, so a page that carries none of them
    // must not blank the controls that offer them.
    if (result.filters) filters = result.filters;
    publish();
  };

  const reload = () => request({ append: false });
  let refresh = null;
  let started = false;
  const refreshSort = () => {
    if (!preferences || !active()) return Promise.resolve();
    if (refresh) return refresh;
    refresh = refreshScreenSort(context.client, preferences, "items").then((notice) => {
      if (!active()) return;
      sortNotice = notice;
      const sort = normalizeItemSort(preferences.sortFor("items"));
      const changed = sort.column !== criteria.sort.column || sort.direction !== criteria.sort.direction;
      if (changed) {
        criteria.sort = sort;
        if (started) return reload();
      }
      if (started) publish();
    }).finally(() => { refresh = null; });
    return refresh;
  };
  const windowNode = context.document.defaultView;
  const onVisible = () => {
    if (context.document.visibilityState === "visible") refreshSort();
  };
  windowNode?.addEventListener?.("focus", refreshSort);
  context.document.addEventListener?.("visibilitychange", onVisible);
  signal?.addEventListener("abort", () => {
    sequence += 1;
    clearTimeout(debounceTimer);
    windowNode?.removeEventListener?.("focus", refreshSort);
    context.document.removeEventListener?.("visibilitychange", onVisible);
  }, { once: true });

  return {
    state,
    start: async () => {
      await refreshSort();
      if (!active()) return;
      criteria.sort = normalizeItemSort(preferences?.sortFor("items"));
      started = true;
      return reload();
    },
    loadMore: () => (cursor === null ? Promise.resolve() : request({
      append: true,
    })),
    // Selecting a criterion resets the sequence immediately: a filter is a
    // deliberate act and should not wait out a text debounce.
    setSort: (column) => {
      const direction = criteria.sort.column === column && criteria.sort.direction === "asc" ? "desc" : "asc";
      criteria.sort = normalizeItemSort({ column, direction });
      const chosen = criteria.sort;
      sortNotice = "";
      preferences?.saveSortFor("items", chosen).then((notice) => {
        if (chosen !== criteria.sort || !active()) return;
        sortNotice = notice;
        publish();
      });
      return reload();
    },
    setFilter: (key, value) => {
      criteria[key] = value;
      return reload();
    },
    // Typing costs a request, so let a burst of keystrokes settle first.
    setQuery: (value) => {
      criteria.query = value;
      if (debounceTimer !== null) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        debounceTimer = null;
        reload();
      }, SEARCH_DEBOUNCE_MS);
    },
  };
}
