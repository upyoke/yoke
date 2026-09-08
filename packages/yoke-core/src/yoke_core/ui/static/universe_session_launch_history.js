import { sessionControlCall } from "./universe_session_control_data.js";

export const HISTORY_PAGE_SIZE = 50;

/** Newest first, ties broken by launch id — the server's page order. */
export function compareLaunches(left, right) {
  const leftTime = String(left.created_at || "");
  const rightTime = String(right.created_at || "");
  if (leftTime !== rightTime) return leftTime < rightTime ? 1 : -1;
  const leftId = String(left.launch_id || "");
  const rightId = String(right.launch_id || "");
  if (leftId === rightId) return 0;
  return leftId < rightId ? 1 : -1;
}

function merged(existing, added) {
  const rows = new Map(existing.map((row) => [String(row.launch_id), row]));
  for (const row of added) rows.set(String(row.launch_id), row);
  return [...rows.values()].sort(compareLaunches);
}

/**
 * Load launch pages across an authorized project scope.
 *
 * Each project pages independently through its own opaque cursor, and the
 * pages are merged newest-first and keyed by launch id, so one project's
 * Load more never drops or repeats another's rows. A superseded request —
 * criteria changed while it was in flight — is discarded by generation
 * rather than allowed to overwrite the newer answer.
 */
export function sessionLaunchPageLoader(context, projects, criteria, onChange) {
  let operational = [];
  let history = [];
  let operationalCount = 0;
  let historyMatchedCount = 0;
  let cursors = new Map();
  let generation = 0;
  let loading = false;
  let failure = null;

  const emit = () => { if (context.isMounted()) onChange(); };

  const requestPage = (project) => sessionControlCall(
    context,
    "session_control.launch.list",
    {
      project,
      limit: HISTORY_PAGE_SIZE,
      ...criteria(),
      ...(cursors.get(project) ? { cursor: cursors.get(project) } : {}),
    },
  );

  const load = async (append) => {
    if (!append) {
      generation += 1;
      operational = [];
      history = [];
      operationalCount = 0;
      historyMatchedCount = 0;
      cursors = new Map();
    }
    const targets = append
      ? projects.filter((project) => cursors.get(project))
      : [...projects];
    const requested = generation;
    loading = true;
    failure = null;
    emit();
    let pages;
    try {
      pages = await Promise.all(targets.map(requestPage));
    } catch (error) {
      if (requested !== generation) return false;
      loading = false;
      failure = error;
      emit();
      return false;
    }
    if (requested !== generation) return false;
    loading = false;
    targets.forEach((project, index) => {
      const page = pages[index] || {};
      if (!append) {
        operational = merged(operational, page.operational || []);
        operationalCount += Number(page.operational_count) || 0;
        historyMatchedCount += Number(page.history_matched_count) || 0;
      }
      history = merged(history, page.history || []);
      cursors.set(project, page.next_cursor || null);
    });
    emit();
    return true;
  };

  return {
    reload: () => load(false),
    loadMore: () => load(true),
    operational: () => operational,
    history: () => history,
    operationalCount: () => operationalCount,
    historyMatchedCount: () => historyMatchedCount,
    hasMore: () => projects.some((project) => Boolean(cursors.get(project))),
    loading: () => loading,
    failure: () => failure,
    /** Discard whatever is in flight; a later response cannot land after this. */
    destroy() { generation += 1; },
  };
}
