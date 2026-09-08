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
  const criteria = { query: "", workflow: "", status: "" };
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
    hasMore: cursor !== null,
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
    if (!context.isMounted()) return;
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

  return {
    state,
    start: reload,
    loadMore: () => (cursor === null ? Promise.resolve() : request({
      append: true,
    })),
    // Selecting a criterion resets the sequence immediately: a filter is a
    // deliberate act and should not wait out a text debounce.
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
